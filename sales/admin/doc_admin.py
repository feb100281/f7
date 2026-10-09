from django.contrib import admin
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils.html import format_html
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import display
from unfold.sections import TableSection

from core.admins import AppModelAdmin, FirstCol
from sales.models import SalesDoc

from .common import ReadOnlyAdminMixin, kind_badge, money, num_cell, qty


class DocLinesSection(TableSection):
    """Раскрывающаяся строка документа: его позиции с текущей товарной группой."""

    related_name = "section_rows"
    fields = ["article_col", "name_col", "group_col", "qty_col", "revenue_col", "cost_col"]

    def __init__(self, request, instance):
        super().__init__(request, instance)
        instance.section_rows = instance.lines.select_related("item", "item__group").order_by("id")

    def article_col(self, obj):
        url = reverse("admin:catalog_item_change", args=[obj.item_id])
        return format_html('<a href="{}" class="f7-link">{}</a>', url, obj.item.article)
    article_col.short_description = "Артикул"

    def name_col(self, obj):
        return format_html('<span class="f7-cell-name">{}</span>', obj.item.name)
    name_col.short_description = "Название"

    def group_col(self, obj):
        return obj.item.group.name if obj.item.group else "—"
    group_col.short_description = "Товарная группа"

    def qty_col(self, obj):
        return num_cell(qty(obj.qty))
    qty_col.short_description = "Кол-во"

    def revenue_col(self, obj):
        return num_cell(money(obj.revenue))
    revenue_col.short_description = "Выручка, ₽"

    def cost_col(self, obj):
        return num_cell(money(obj.cost))
    cost_col.short_description = "Себест., ₽"


@admin.register(SalesDoc)
class SalesDocAdmin(ReadOnlyAdminMixin, AppModelAdmin):
    list_sections = [DocLinesSection]
    list_per_page = 50
    date_hierarchy = "date"

    list_display = ["doc_col", "kind_col", "department", "lines_col", "qty_col", "revenue_col"]
    list_display_links = None
    list_select_related = ["department"]
    list_filter = [
        ("kind", ChoicesDropdownFilter),
        ("department", RelatedDropdownFilter),
        ("date", RangeDateFilter),
    ]
    search_fields = ["number", "lines__item__article"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            lines_n=Count("lines"),
            qty_sum=Sum("lines__qty"),
            revenue_sum=Sum("lines__revenue"),
        )

    @display(description="Документ", ordering="dt")
    def doc_col(self, obj):
        return FirstCol(obj.number, f"{obj.dt:%d.%m.%Y %H:%M} · {obj.doc_type}").name_subtext

    @display(description="Канал", ordering="kind")
    def kind_col(self, obj):
        return kind_badge(obj.kind)

    @display(description="Строк", ordering="lines_n")
    def lines_col(self, obj):
        return num_cell(str(obj.lines_n))

    @display(description="Кол-во", ordering="qty_sum")
    def qty_col(self, obj):
        return num_cell(qty(obj.qty_sum))

    @display(description="Выручка, ₽", ordering="revenue_sum")
    def revenue_col(self, obj):
        return num_cell(money(obj.revenue_sum))
