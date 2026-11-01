"""
Остатки в админке.

    «Остатки на дату» — список срезов со сводкой; «Добавить» = загрузить файл из 1С и указать дату
        (дата по умолчанию — из имени файла). Повторная загрузка на ту же дату заменяет срез.
        ?next=<адрес> — куда вернуться после загрузки (кнопка на «Расчёте заказа»).
    «Строки остатков» — строки среза (по умолчанию последнего), выбор даты, «все даты» — история;
        над списком — плитки по выбранному срезу.
    На карточке артикула — вкладка «Остатки по датам».
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme
from datetime import timedelta

from django.db.models import F, Q
from unfold.contrib.filters.admin import DropdownFilter, RelatedDropdownFilter
from unfold.decorators import display

from catalog.admin.common import money, qty
from core.admins import AppModelAdmin, AppTabularInline
from stock.models import StockLine, StockSnapshot
from stock.services.load import DEAD_DAYS, StockFileError, date_from_filename, load, order_summary, read_file


def _pct(a, b) -> str:
    return f"{a / b:.0%}" if b else "—"


class UploadForm(forms.ModelForm):
    upload = forms.FileField(label="Файл остатков из 1С (.xlsx)",
                             help_text="Колонки «Артикул», «Номенклатура», «Доступно», «Поступит» — как в выгрузке 1С.")

    class Meta:
        model = StockSnapshot
        fields = ["date", "note"]
        help_texts = {"date": "Можно не заполнять, если дата есть в имени файла (…16.10.2026.xlsx). "
                              "Срез на эту дату уже есть — заменится."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].required = False
        self.order_fields(["upload", "date", "note"])

    def validate_unique(self):
        pass  # срез на ту же дату заменяется при сохранении

    def clean(self):
        data = super().clean()
        f = data.get("upload")
        if not f:
            return data
        if not data.get("date"):
            d = date_from_filename(f.name)
            if not d:
                raise forms.ValidationError("В имени файла нет даты — укажите «Остатки на дату».")
            data["date"] = d
        try:
            self.rows_n = len(read_file(f))
        except StockFileError as e:
            raise forms.ValidationError(str(e)) from e
        f.seek(0)
        return data


@admin.register(StockSnapshot)
class StockSnapshotAdmin(AppModelAdmin):
    list_display = ["date_col", "lines_col", "available_col", "incoming_col", "value_col", "dead_col", "order_col",
                    "uploaded_col"]
    list_display_links = ["date_col"]
    readonly_fields = ["date", "filename", "uploaded", "uploaded_by", "lines_col", "available_col", "incoming_col",
                       "value_col", "dead_col", "negative_col", "order_col", "lines_link"]
    fieldsets = [
        (None, {"fields": ["date", "note", ("filename", "uploaded", "uploaded_by")]}),
        ("Сводка", {"fields": ["lines_col", "available_col", "incoming_col", "value_col", "dead_col", "negative_col",
                               "order_col", "lines_link"]}),
    ]

    def get_form(self, request, obj=None, change=False, **kwargs):
        if obj is None:
            kwargs["form"] = UploadForm
        return super().get_form(request, obj, change=change, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return [(None, {"fields": ["upload", "date", "note"]})]
        return self.fieldsets

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj else []

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        f = form.cleaned_data["upload"]
        snap, replaced = load(f, form.cleaned_data["date"], filename=f.name, user=request.user,
                              note=form.cleaned_data.get("note") or "")
        obj.pk = snap.pk
        obj._replaced = replaced

    def log_addition(self, request, obj, message):
        return None  # срез сохраняет загрузчик, а не форма

    def response_add(self, request, obj, post_url_continue=None):
        snap = StockSnapshot.objects.get(pk=obj.pk)
        verb = "заменены" if getattr(obj, "_replaced", False) else "загружены"
        messages.success(request, (
            f"Остатки на {snap.date:%d.%m.%Y} {verb}: {snap.lines_n} арт., из них в номенклатуре "
            f"{snap.matched_n}. Доступно {qty(snap.available)} шт. (≈{money(snap.value)} ₽ по с/с), "
            f"в пути {qty(snap.incoming)} шт."))
        lines = reverse("admin:stock_stockline_changelist")
        nxt = request.GET.get("next")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) \
                and not nxt.startswith(lines):
            sep = "&" if "?" in nxt else "?"
            return HttpResponseRedirect(f"{nxt}{sep}stock={snap.pk}")
        return HttpResponseRedirect(f"{lines}?date={snap.pk}")  # по умолчанию — строки загруженного среза

    # --- колонки
    @display(description="Остатки на дату", ordering="date")
    def date_col(self, obj):
        return format_html('<b>{}</b><br><span class="f7-field-sub">{}</span>', f"{obj.date:%d.%m.%Y}",
                           obj.filename or "")

    @display(description="Артикулов · в номенклатуре")
    def lines_col(self, obj):
        return format_html("{} · {} <span class=\"f7-field-sub\">({})</span>", qty(obj.lines_n), qty(obj.matched_n),
                           _pct(obj.matched_n, obj.lines_n))

    @display(description="Доступно, шт.")
    def available_col(self, obj):
        return qty(obj.available)

    @display(description="Поступит, шт.")
    def incoming_col(self, obj):
        return qty(obj.incoming)

    @display(description="Доступно по с/с, ₽")
    def value_col(self, obj):
        return format_html('{}<br><span class="f7-field-sub">с/с известна у {} арт.</span>', money(obj.value),
                           qty(obj.value_known_n))

    @display(description="Без продаж больше года")
    def dead_col(self, obj):
        return format_html('{} арт. · {} шт.<br><span class="f7-field-sub">≈{} ₽ по с/с (где известна)</span>',
                           qty(obj.dead_n), qty(obj.dead_qty), money(obj.dead_value))

    @display(description="Отрицательный остаток, арт.")
    def negative_col(self, obj):
        return qty(obj.negative_n)

    @display(description="К заказу")
    def order_col(self, obj):
        if not obj.order_run_id:
            return "—"
        url = reverse("forecast_dashboard_qty") + f"?stock={obj.pk}"
        return format_html('<a class="f7-link" href="{}">{} арт. · {} шт.</a><br><span class="f7-field-sub">≈{} ₽ по с/с</span>',
                           url, qty(obj.order_n), qty(obj.order_qty), money(obj.order_cost))

    def changelist_view(self, request, extra_context=None):
        last = StockSnapshot.objects.first()
        if last:
            order_summary(last)  # новый прогноз → цифры «к заказу» у последнего среза обновятся
        return super().changelist_view(request, extra_context)

    @display(description="Загружен")
    def uploaded_col(self, obj):
        return format_html('{}<br><span class="f7-field-sub">{}</span>', f"{obj.uploaded:%d.%m.%Y %H:%M}",
                           obj.uploaded_by or "")

    @display(description="Строки")
    def lines_link(self, obj):
        url = reverse("admin:stock_stockline_changelist") + f"?date={obj.pk}"
        return format_html('<a class="f7-link" href="{}">Открыть {} строк →</a>', url, qty(obj.lines_n))


class DateFilter(DropdownFilter):
    """Срез остатков. По умолчанию — последний; «Все даты» — история артикула по срезам."""

    title = "Остатки на дату"
    parameter_name = "date"
    ALL = "all"
    all_option = None  # пустое значение = последний срез, «Все даты» — отдельным пунктом

    def lookups(self, request, model_admin):
        return [(str(pk), f"{d:%d.%m.%Y}") for pk, d in StockSnapshot.objects.values_list("pk", "date")] + \
            [(self.ALL, "Все даты")]

    def value(self):
        v = super().value()
        if v:
            return v
        last = StockSnapshot.objects.values_list("pk", flat=True).first()
        return str(last) if last else None

    def queryset(self, request, qs):
        v = self.value()
        if v and v != self.ALL:
            return qs.filter(snapshot_id=v)
        return qs

    @classmethod
    def snapshot(cls, request) -> StockSnapshot | None:
        v = request.GET.get(cls.parameter_name)
        if v == cls.ALL:
            return None
        if v and v.isdigit():
            return StockSnapshot.objects.filter(pk=v).first()
        return StockSnapshot.objects.first()


class StateFilter(DropdownFilter):
    title = "Что показать"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [
            ("on_hand", "Есть на складе"),
            ("incoming", "Едет (в пути)"),
            ("dead", "Без продаж больше года"),
            ("never", "Нет в номенклатуре (не продавался 5 лет)"),
            ("negative", "Отрицательный остаток"),
        ]

    def queryset(self, request, qs):
        v = self.value()
        if v == "on_hand":
            return qs.filter(available__gt=0)
        if v == "incoming":
            return qs.filter(incoming__gt=0)
        if v == "dead":
            return qs.filter(available__gt=0).filter(
                Q(last_sale__isnull=True) | Q(last_sale__lt=F("snapshot__date") - timedelta(days=DEAD_DAYS)))
        if v == "never":
            return qs.filter(item=None)
        if v == "negative":
            return qs.filter(available__lt=0)
        return qs


class GroupFilter(RelatedDropdownFilter):
    title = "Товарная группа"


@admin.register(StockLine)
class StockLineAdmin(AppModelAdmin):
    list_before_template = "stock/admin/line_kpis.html"
    list_display = ["article_col", "name_col", "group_col", "snapshot_col", "available_col", "incoming_col",
                    "cost_col", "value_col", "last_sale_col"]
    list_display_links = None
    list_filter = [DateFilter, StateFilter, ("item__group", GroupFilter)]
    list_select_related = ["snapshot", "item", "item__group"]
    search_fields = ["article", "name", "item__name"]
    list_per_page = 100
    ordering = ["-snapshot__date", "article"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_list_display(self, request):
        cols = list(super().get_list_display(request))
        if request.GET.get(DateFilter.parameter_name) != DateFilter.ALL:
            cols.remove("snapshot_col")  # один срез — дата в шапке, колонка не нужна
        return cols

    def changelist_view(self, request, extra_context=None):
        snap = DateFilter.snapshot(request)
        params = [(k, v) for k, v in request.GET.items() if k not in (DateFilter.parameter_name, "p")]
        extra_context = {**(extra_context or {}), "stock_snap": snap, "stock_kpis": self._kpis(snap),
                         "stock_dates": list(StockSnapshot.objects.values_list("pk", "date")),
                         "stock_date": request.GET.get(DateFilter.parameter_name) or (str(snap.pk) if snap else ""),
                         "stock_params": params,
                         "stock_upload_url": reverse("admin:stock_stocksnapshot_add")
                         if request.user.has_perm("stock.add_stocksnapshot") else None}
        return super().changelist_view(request, extra_context)

    @staticmethod
    def _kpis(snap: StockSnapshot | None) -> list[dict]:
        if snap is None:
            return []
        base = reverse("admin:stock_stockline_changelist") + f"?date={snap.pk}"
        kpis = [
            {"title": "На складе по с/с", "value": f"{money(snap.value)} ₽", "url": f"{base}&state=on_hand",
             "sub": f"{money(snap.available)} шт. · {qty(snap.lines_n)} арт., "
                    f"в номенклатуре {qty(snap.matched_n)} ({_pct(snap.matched_n, snap.lines_n)})"},
            {"title": "В пути", "value": f"{money(snap.incoming)} шт.", "url": f"{base}&state=incoming",
             "sub": "уже заказано и едет"},
            {"title": "Без продаж больше года", "value": f"{qty(snap.dead_n)} арт.", "warn": bool(snap.dead_n),
             "url": f"{base}&state=dead", "sub": f"{money(snap.dead_qty)} шт., ≈{money(snap.dead_value)} ₽ по с/с"},
        ]
        if snap.order_run_id:
            p = snap.order_params or {}
            kpis.append({"title": "К заказу", "value": f"{qty(snap.order_n)} арт.",
                         "url": reverse("forecast_dashboard_qty") + f"?stock={snap.pk}",
                         "sub": f"{money(snap.order_qty)} шт., ≈{money(snap.order_cost)} ₽ · "
                                f"поставка {p.get('lt')} + {p.get('rv')} мес."})
        return kpis

    @display(description="Артикул", ordering="article")
    def article_col(self, obj):
        if obj.item_id:
            return format_html('<a class="f7-link" href="{}">{}</a>',
                               reverse("admin:catalog_item_change", args=[obj.item_id]), obj.article)
        return format_html('{}<br><span class="f7-field-sub">нет в номенклатуре</span>', obj.article)

    @display(description="Название", ordering="name")
    def name_col(self, obj):
        name = obj.item.name if obj.item_id else obj.name
        return format_html('<span class="f7-ellipsis" title="{}">{}</span>', obj.name, name)

    @display(description="Группа", ordering="item__group__name")
    def group_col(self, obj):
        return obj.item.group.name if obj.item_id and obj.item.group_id else "—"

    @display(description="На дату", ordering="snapshot__date")
    def snapshot_col(self, obj):
        return f"{obj.snapshot.date:%d.%m.%Y}"

    @display(description="Доступно", ordering="available")
    def available_col(self, obj):
        if obj.available < 0:
            return format_html('<b style="color:#D3141C">{}</b>', qty(obj.available))
        return qty(obj.available)

    @display(description="В пути", ordering="incoming")
    def incoming_col(self, obj):
        return qty(obj.incoming) if obj.incoming else "—"

    @display(description="С/с, ₽/шт.", ordering="cost")
    def cost_col(self, obj):
        return money(obj.cost)

    @display(description="Доступно по с/с, ₽")
    def value_col(self, obj):
        return money(obj.cost * obj.available) if obj.cost and obj.available > 0 else "—"

    @display(description="Последняя продажа", ordering="last_sale")
    def last_sale_col(self, obj):
        if not obj.last_sale:
            return format_html('<span class="f7-field-sub">{}</span>', "не продавался" if obj.item_id else "—")
        old = obj.available > 0 and obj.last_sale < obj.snapshot.date - timedelta(days=DEAD_DAYS)
        return format_html('<span{}>{}</span>', ' style="color:#8A5A0B" title="Больше года без продаж"' if old else "",
                           f"{obj.last_sale:%d.%m.%Y}")


class StockHistoryInline(AppTabularInline):
    """Вкладка «Остатки по датам» на карточке артикула."""

    model = StockLine
    fk_name = "item"
    fields = ["snapshot", "available", "incoming"]
    readonly_fields = fields
    verbose_name = "срез"
    verbose_name_plural = "Остатки по датам"
    show_change_link = False
    can_delete = False
    ordering = ["-snapshot__date"]

    def has_add_permission(self, request, obj=None):
        return False


# вкладка на карточке артикула — без правки catalog/admin
_item_admin = admin.site._registry.get(__import__("catalog.models", fromlist=["Item"]).Item)
if _item_admin is not None and StockHistoryInline not in _item_admin.inlines:
    _item_admin.inlines = [*_item_admin.inlines, StockHistoryInline]
