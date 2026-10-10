"""
Замены номеров: старый артикул → новый (тот же товар). Действующие замены склеивают
артикулы в семейство — прогноз в штуках, статистика спроса и «год назад» идут по семейству
и ставятся на актуальный номер.

Менеджер:
    • подтверждает или отклоняет предложения (номер в названии) — действия в списке;
    • заводит свою пару — «Добавить» (источник «Вручную»);
    • отключает неверную пару правила — «Отклонить» (правило её больше не создаст).
После любого изменения семейства пересобираются сразу.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django import forms
from django.db.models import Case, IntegerField, Value, When
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.contrib.filters.admin import ChoicesDropdownFilter
from unfold.decorators import action, display

from catalog.models import Item, ItemReplacement, ReplacementSource as Src, ReplacementStatus as St
from catalog.services.replacements import rebuild_families
from core.admins import AppModelAdmin, Badge

from .common import qty

SOURCE_BADGES = {
    Src.RULE_9X: ("X → 9X", "looks_one", "info"),
    Src.OIL: ("Масла/химия", "water_drop", "info"),
    Src.NAME: ("Номер в названии", "text_fields", "gray"),
    Src.MANUAL: ("Вручную", "person", "primary"),
    Src.CLIENT: ("Клиент", "handshake", "primary"),
}
STATUS_BADGES = {
    St.ACTIVE: ("check_circle", "success"),
    St.SUGGESTED: ("help", "warning"),
    St.REJECTED: ("block", "gray"),
}


ARROW = mark_safe('<span class="material-symbols-outlined f7-field-sub">arrow_forward</span>')


def item_cell(item: Item, sub: str):
    url = reverse("admin:catalog_item_change", args=[item.pk])
    return format_html(
        '<span class="f7-field-stack"><a class="f7-link" href="{}">{}</a>'
        '<span class="f7-field-sub" title="{}">{}</span><span class="f7-field-sub">{}</span></span>',
        url, item.article, item.name, item.name, sub,
    )


def sales_sub(item: Item) -> str:
    if not item.last_sale:
        return "продаж нет"
    return (f"{qty(item.qty)} шт., "
            f"{item.first_sale:%m.%Y} – {item.last_sale:%m.%Y}")


def _refresh(request):
    r = rebuild_families(log=lambda *_: None)
    if r["changed"]:
        messages.info(request, f"Семейства пересобраны: изменилось артикулов — {r['changed']}")


class ReplacementForm(forms.ModelForm):
    class Meta:
        model = ItemReplacement
        fields = ["old", "new", "status", "note"]

    def clean(self):
        data = super().clean()
        old, new = data.get("old"), data.get("new")
        if old and new:
            if old == new:
                raise forms.ValidationError("Старый и новый номер совпадают")
            back = ItemReplacement.objects.filter(old=new, new=old)
            if back.exists():
                raise forms.ValidationError(f"Уже есть обратная замена {new.article} → {old.article} — "
                                            "поменяйте её или отклоните")
        return data


@admin.register(ItemReplacement)
class ItemReplacementAdmin(AppModelAdmin):
    form = ReplacementForm
    list_before_template = "catalog/admin/replacement_kpis.html"
    list_per_page = 100
    list_display = ["old_col", "arrow_col", "new_col", "source_col", "status_col", "note_col"]
    list_display_links = None
    list_filter = [("status", ChoicesDropdownFilter), ("source", ChoicesDropdownFilter)]
    list_select_related = ["old", "new"]
    search_fields = ["old__article", "new__article", "old__name", "new__name"]
    autocomplete_fields = ["old", "new"]
    fields = [("old", "new"), "status", "note", "source"]
    readonly_fields = ["source"]
    actions = ["confirm", "reject"]

    def get_queryset(self, request):
        # сначала то, что ждёт решения
        return super().get_queryset(request).annotate(
            st_order=Case(When(status=St.SUGGESTED, then=Value(0)), When(status=St.ACTIVE, then=Value(1)),
                          default=Value(2), output_field=IntegerField()),
        ).order_by("st_order", "source", "new__article")

    def get_readonly_fields(self, request, obj=None):
        return ["source"] if obj else []

    def get_fields(self, request, obj=None):
        return self.fields if obj else [("old", "new"), "status", "note"]

    # --- колонки
    @display(description="Старый номер")
    def old_col(self, obj):
        return item_cell(obj.old, sales_sub(obj.old))

    @display(description="")
    def arrow_col(self, obj):
        return ARROW

    @display(description="Актуальный номер")
    def new_col(self, obj):
        return item_cell(obj.new, sales_sub(obj.new))

    @display(description="Откуда", ordering="source")
    def source_col(self, obj):
        label, icon, style = SOURCE_BADGES.get(obj.source, ("—", "help", "gray"))
        return Badge(label, icon, style, title=obj.get_source_display()).badge

    @display(description="Статус", ordering="status")
    def status_col(self, obj):
        icon, style = STATUS_BADGES.get(obj.status, ("help", "gray"))
        return Badge(obj.get_status_display(), icon, style).badge

    @display(description="Комментарий")
    def note_col(self, obj):
        return format_html('<span class="f7-cell-name f7-field-sub" title="{}">{}</span>', obj.note, obj.note or "")

    # --- сохранение: ручная пара, проверка, пересборка семейств
    def save_model(self, request, obj, form, change):
        if not change:
            obj.source = Src.MANUAL
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        _refresh(request)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        _refresh(request)
        return super().response_change(request, obj)

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        _refresh(request)

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        _refresh(request)

    # --- действия
    @action(description="Подтвердить — склеить в семейство")
    def confirm(self, request, queryset):
        n = queryset.exclude(status=St.ACTIVE).update(status=St.ACTIVE)
        messages.success(request, f"Подтверждено замен: {n}")
        _refresh(request)

    @action(description="Отклонить — это разные товары")
    def reject(self, request, queryset):
        n = queryset.exclude(status=St.REJECTED).update(status=St.REJECTED)
        messages.success(request, f"Отклонено замен: {n} (правила их больше не предложат)")
        _refresh(request)

    # --- плитки над списком
    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "rep_kpis": self._kpis()}
        return super().changelist_view(request, extra_context)

    @staticmethod
    def _kpis() -> list[dict]:
        base = reverse("admin:catalog_itemreplacement_changelist")
        items = reverse("admin:catalog_item_changelist")
        reps = ItemReplacement.objects.all()
        heads = Item.objects.filter(family_members__isnull=False).distinct().count()
        members = Item.objects.exclude(family_head=None).count()
        waiting = reps.filter(status=St.SUGGESTED).count()
        rule = reps.filter(status=St.ACTIVE, source__in=[Src.RULE_9X, Src.OIL]).count()
        own = reps.filter(status=St.ACTIVE, source__in=[Src.MANUAL, Src.CLIENT, Src.NAME]).count()
        rejected = reps.filter(status=St.REJECTED).count()
        return [
            {"title": "Семейств", "value": heads, "url": f"{items}?family=head",
             "sub": f"старых номеров в них: {members}"},
            {"title": "Ждут решения", "value": waiting, "warn": bool(waiting),
             "url": f"{base}?status__exact={St.SUGGESTED}", "sub": "номер в названии — проверьте"},
            {"title": "По правилам", "value": rule, "url": f"{base}?status__exact={St.ACTIVE}",
             "sub": "X → 9X и масла/химия"},
            {"title": "Решения менеджера", "value": own, "sub": f"отклонено: {rejected}"},
        ]
