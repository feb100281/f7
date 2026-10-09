"""
Админки витрин — только просмотр. Если витрина ещё не построена (таблицы нет),
вместо ошибки — сообщение и переход к списку команд.
"""

from django.contrib import admin, messages
from django.db import DatabaseError
from django.shortcuts import redirect
from django.urls import reverse
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import display

from catalog.admin.common import money, num_cell, qty
from catalog.models import DemandType
from core.admins import AppModelAdmin, FirstCol
from marts.models import MartItemMonth
from sales.admin.common import ReadOnlyAdminMixin, kind_badge


class MartAdmin(ReadOnlyAdminMixin, AppModelAdmin):
    list_display_links = None
    list_per_page = 100

    def changelist_view(self, request, extra_context=None):
        try:
            response = super().changelist_view(request, extra_context)
            if hasattr(response, "render"):
                response.render()
            return response
        except DatabaseError:
            messages.warning(
                request,
                f"Витрина «{self.model._meta.verbose_name_plural}» ещё не построена — "
                "запустите команду «Пересчитать витрины».",
            )
            return redirect(reverse("admin:core_jobs_changelist"))


class DemandTypeFilter(admin.SimpleListFilter):
    title = "Тип спроса"
    parameter_name = "demand"

    def lookups(self, request, model_admin):
        return DemandType.choices

    def queryset(self, request, queryset):
        return queryset.filter(item__group__demand_type=self.value()) if self.value() else queryset


@admin.register(MartItemMonth)
class MartItemMonthAdmin(MartAdmin):
    """Группа — через артикул (текущая), в витрине не хранится."""

    list_display = ["month_col", "item_col", "group_col", "kind_col", "department", "qty_col", "revenue_col", "docs"]
    list_select_related = ["item", "item__group", "department"]
    list_filter = [
        ("item__group", RelatedDropdownFilter),
        DemandTypeFilter,
        ("item__platform", RelatedDropdownFilter),
        ("kind", ChoicesDropdownFilter),
        ("department", RelatedDropdownFilter),
        ("month", RangeDateFilter),
    ]
    search_fields = ["item__article", "item__name"]
    ordering = ["-month", "-revenue"]

    @display(description="Месяц", ordering="month")
    def month_col(self, obj):
        return f"{obj.month:%m.%Y}"

    @display(description="Артикул", ordering="item__article")
    def item_col(self, obj):
        return FirstCol(obj.item.name, obj.item.article).name_subtext

    @display(description="Товарная группа", ordering="item__group__sort")
    def group_col(self, obj):
        return obj.item.group.name if obj.item.group else "—"

    @display(description="Канал", ordering="kind")
    def kind_col(self, obj):
        return kind_badge(obj.kind)

    @display(description="Кол-во", ordering="qty")
    def qty_col(self, obj):
        return num_cell(qty(obj.qty))

    @display(description="Выручка, ₽", ordering="revenue")
    def revenue_col(self, obj):
        return num_cell(money(obj.revenue))
