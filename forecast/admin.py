"""
Админки прогноза — только просмотр. Подбор параметров раскрывается в списке:
лучшие комбинации с ошибкой на 1–3 мес. и на всём горизонте.
"""

from __future__ import annotations

from django.contrib import admin
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RelatedDropdownFilter
from unfold.decorators import display
from unfold.sections import TableSection

from catalog.admin.common import money, num_cell
from core.admins import AppModelAdmin, FirstCol
from forecast.models import ForecastGroup, ForecastItem, ForecastRun, TuneRun
from forecast.services.engine import params_label
from sales.admin.common import ReadOnlyAdminMixin

SECTION_LIMIT = 25


def _sum_error(folds) -> float | None:
    """Средняя по датам проверки ошибка суммы за горизонт (|прогноз − факт| / факт)."""
    errs = [abs(f["yhat"] - f["actual"]) / f["actual"] for f in folds or [] if f.get("actual")]
    return sum(errs) / len(errs) if errs else None


def _pct(v):
    return "—" if v is None else f"{v:.1%}".replace(".", ",")


class TuneResultsSection(TableSection):
    verbose_name = None
    related_name = "section_rows"
    fields = ["rank_col", "params_col", "sum_col", "wape3_col", "wape6_col", "bias_col", "folds_col"]

    def __init__(self, request, instance):
        super().__init__(request, instance)
        instance.section_rows = instance.results.filter(
            Q(rank__lte=SECTION_LIMIT) | Q(is_default=True)
        ).order_by("rank")

    def rank_col(self, obj):
        return format_html("<b>{}</b>{}", obj.rank, " · по умолчанию" if obj.is_default else "")
    rank_col.short_description = "Место"

    def params_col(self, obj):
        return params_label(obj.params)
    params_col.short_description = "Параметры"

    def sum_col(self, obj):
        return _pct(_sum_error(obj.folds))
    sum_col.short_description = "Ошибка суммы за горизонт"

    def wape3_col(self, obj):
        return _pct(obj.wape3)
    wape3_col.short_description = "WAPE 1–3 мес."

    def wape6_col(self, obj):
        return _pct(obj.wape6)
    wape6_col.short_description = "WAPE на горизонте"

    def bias_col(self, obj):
        return _pct(obj.bias)
    bias_col.short_description = "Смещение"

    def folds_col(self, obj):
        return " · ".join(f"{f['cutoff'][5:7]}.{f['cutoff'][2:4]}: {_pct(f['wape'])}" for f in obj.folds)
    folds_col.short_description = "По датам отсечки"


@admin.register(TuneRun)
class TuneRunAdmin(ReadOnlyAdminMixin, AppModelAdmin):
    list_display = ["created_col", "series", "best_col", "sum_col", "wape3_col", "wape6_col", "default_col", "cutoffs_col",
                    "combos", "seconds_col"]
    list_filter = [("series", ChoicesDropdownFilter)]
    list_sections = [TuneResultsSection]
    list_display_links = None

    def has_delete_permission(self, request, obj=None):
        return True  # старые подборы можно удалять

    @display(description="Когда", ordering="created")
    def created_col(self, obj):
        return f"{timezone.localtime(obj.created):%d.%m.%Y %H:%M}"

    @display(description="Лучшие параметры")
    def best_col(self, obj):
        return params_label(obj.best) if obj.best else "—"

    @display(description="Ошибка суммы за горизонт")
    def sum_col(self, obj):
        best = obj.results.order_by("rank").first()
        return _pct(_sum_error(best.folds)) if best else "—"

    @display(description="WAPE 1–3 мес.", ordering="wape3")
    def wape3_col(self, obj):
        return _pct(obj.wape3)

    @display(description="WAPE на горизонте", ordering="wape6")
    def wape6_col(self, obj):
        return _pct(obj.wape6)

    @display(description="WAPE Prophet по умолчанию")
    def default_col(self, obj):
        return f"{_pct(obj.default_wape3)} / {_pct(obj.default_wape6)}"

    @display(description="Отсечки")
    def cutoffs_col(self, obj):
        return f"{len(obj.cutoffs)}: {obj.cutoffs[0][:7]} … {obj.cutoffs[-1][:7]}" if obj.cutoffs else "—"

    @display(description="Время")
    def seconds_col(self, obj):
        return f"{obj.seconds / 60:.1f} мин" if obj.seconds >= 60 else f"{obj.seconds:.0f} c"


@admin.register(ForecastRun)
class ForecastRunAdmin(ReadOnlyAdminMixin, AppModelAdmin):
    list_display = ["created_col", "data_end", "horizon", "params_col", "note", "open_col"]
    list_display_links = None

    def has_delete_permission(self, request, obj=None):
        return True

    @display(description="Когда", ordering="created")
    def created_col(self, obj):
        return f"{timezone.localtime(obj.created):%d.%m.%Y %H:%M}"

    @display(description="Параметры")
    def params_col(self, obj):
        return format_html_join(mark_safe("<br>"), "{}: {}", ((k, params_label(v)) for k, v in obj.params.items()))

    @display(description="")
    def open_col(self, obj):
        url = reverse("forecast_dashboard_overview") + f"?run={obj.pk}"
        return format_html('<a href="{}" class="f7-link">открыть →</a>', url)


class LadderAdmin(ReadOnlyAdminMixin, AppModelAdmin):
    """Результаты лестницы — только просмотр; удобнее смотреть в «Прогноз → Штуки»."""

    list_display_links = None
    list_per_page = 100

    @display(description="Месяц", ordering="month")
    def month_col(self, obj):
        return f"{obj.month:%m.%Y}"

    @display(description="Прогноз, шт.", ordering="qty")
    def qty_col(self, obj):
        return num_cell(f"{obj.qty:,.1f}".replace(",", " ").replace(".", ","))

    @display(description="Выручка, ₽", ordering="revenue")
    def revenue_col(self, obj):
        return num_cell(money(obj.revenue))


@admin.register(ForecastGroup)
class ForecastGroupAdmin(LadderAdmin):
    list_display = ["month_col", "series", "group", "share_col", "revenue_col", "qty_col", "run"]
    list_select_related = ["group", "run"]
    list_filter = [("run", RelatedDropdownFilter), ("series", ChoicesDropdownFilter), ("group", RelatedDropdownFilter)]
    ordering = ["-run", "month", "-revenue"]

    @display(description="Доля в ряду", ordering="share")
    def share_col(self, obj):
        return num_cell(_pct(obj.share))


@admin.register(ForecastItem)
class ForecastItemAdmin(LadderAdmin):
    list_display = ["month_col", "series", "item_col", "group", "qty_col", "revenue_col", "price_col", "run"]
    list_select_related = ["item", "group", "run"]
    list_filter = [("run", RelatedDropdownFilter), ("series", ChoicesDropdownFilter),
                   ("group", RelatedDropdownFilter), ("price_source", ChoicesDropdownFilter)]
    search_fields = ["item__article", "item__name"]
    ordering = ["-run", "month", "-qty"]

    @display(description="Артикул", ordering="item__article")
    def item_col(self, obj):
        return FirstCol(obj.item.name, obj.item.article).name_subtext

    @display(description="Цена", ordering="price")
    def price_col(self, obj):
        return num_cell(money(obj.price), obj.get_price_source_display())
