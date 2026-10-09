from django.contrib import admin
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import display

from catalog.models import DemandType
from core.admins import AppModelAdmin, FirstCol
from sales.models import SalesLine

from .common import ReadOnlyAdminMixin, kind_badge, money, num_cell, qty


class DemandTypeFilter(admin.SimpleListFilter):
    title = "Тип спроса"
    parameter_name = "demand"

    def lookups(self, request, model_admin):
        return DemandType.choices

    def queryset(self, request, queryset):
        return queryset.filter(item__group__demand_type=self.value()) if self.value() else queryset


@admin.register(SalesLine)
class SalesLineAdmin(ReadOnlyAdminMixin, AppModelAdmin):
    """
    Строки продаж. Товарная группа и тип спроса — через артикул: перенёс артикул
    в другую группу — фильтр «Товарная группа» сразу покажет его продажи в новой группе.
    """

    list_per_page = 100
    list_display = ["date_col", "doc_col", "kind_col", "item_col", "group_col", "qty_col", "revenue_col", "cost_col"]
    list_display_links = None
    list_select_related = ["doc", "doc__department", "item", "item__group"]
    list_filter = [
        ("item__group", RelatedDropdownFilter),
        DemandTypeFilter,
        ("item__platform", RelatedDropdownFilter),
        ("doc__kind", ChoicesDropdownFilter),
        ("doc__department", RelatedDropdownFilter),
        ("doc__date", RangeDateFilter),
    ]
    search_fields = ["item__article", "item__name", "doc__number"]
    ordering = ["-doc__dt", "id"]

    @display(description="Дата", ordering="doc__dt")
    def date_col(self, obj):
        return f"{obj.doc.dt:%d.%m.%Y}"

    @display(description="Документ", ordering="doc__number")
    def doc_col(self, obj):
        return FirstCol(obj.doc.number, obj.doc.department.prefix if obj.doc.department else "").name_subtext

    @display(description="Канал", ordering="doc__kind")
    def kind_col(self, obj):
        return kind_badge(obj.doc.kind)

    @display(description="Артикул", ordering="item__article")
    def item_col(self, obj):
        return FirstCol(obj.item.name, obj.item.article).name_subtext

    @display(description="Товарная группа", ordering="item__group__sort")
    def group_col(self, obj):
        return obj.item.group.name if obj.item.group else "—"

    @display(description="Кол-во", ordering="qty")
    def qty_col(self, obj):
        return num_cell(qty(obj.qty))

    @display(description="Выручка, ₽", ordering="revenue")
    def revenue_col(self, obj):
        return num_cell(money(obj.revenue))

    @display(description="Себест., ₽", ordering="cost")
    def cost_col(self, obj):
        return num_cell(money(obj.cost))
