"""
Товарные группы. В списке каждая группа раскрывается (Unfold list_sections) —
менеджер сразу видит её артикулы по убыванию выручки, не уходя со страницы.
"""

from __future__ import annotations

from django.contrib import admin
from django.db.models import Count, FloatField, Q, Sum, Value
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.contrib.filters.admin import ChoicesDropdownFilter
from unfold.decorators import display
from unfold.sections import TableSection

from catalog.models import GroupSource, Item, ItemGroup
from core.admins import AppModelAdmin, FirstCol

from .common import demand_badge, money, num_cell, qty, source_badge

SECTION_LIMIT = 25


class GroupItemsSection(TableSection):
    """Раскрывающаяся строка группы: топ артикулов по выручке + ссылка на все."""

    verbose_name = None
    related_name = "section_rows"
    fields = ["article_col", "name_col", "platform_col", "revenue_col", "months_col", "last_sale_col", "source_col"]

    def __init__(self, request, instance):
        super().__init__(request, instance)
        instance.section_rows = (
            instance.items.select_related("platform").order_by("-revenue")[:SECTION_LIMIT]
        )

    # --- колонки
    def article_col(self, obj):
        url = reverse("admin:catalog_item_change", args=[obj.pk])
        return format_html('<a href="{}" class="f7-link">{}</a>', url, obj.article)
    article_col.short_description = "Артикул"

    def name_col(self, obj):
        return format_html('<span class="f7-cell-name" title="{}">{}</span>', obj.name_1c or obj.name, obj.name)
    name_col.short_description = "Название"

    def platform_col(self, obj):
        return obj.platform.name if obj.platform else "—"
    platform_col.short_description = "Техника"

    def revenue_col(self, obj):
        return num_cell(money(obj.revenue))
    revenue_col.short_description = "Выручка, ₽"

    def months_col(self, obj):
        return num_cell(str(obj.months))
    months_col.short_description = "Мес. с продажами"

    def last_sale_col(self, obj):
        return obj.last_sale.strftime("%d.%m.%Y") if obj.last_sale else "—"
    last_sale_col.short_description = "Последняя продажа"

    def source_col(self, obj):
        return source_badge(obj)
    source_col.short_description = "Группа определена"

    def render(self) -> str:
        total = getattr(self.instance, "items_n", None)
        if total is None:
            total = self.instance.items.count()
        if not total:
            return mark_safe('<div class="f7-mini-note">В группе пока нет артикулов</div>')

        html = super().render()
        url = reverse("admin:catalog_item_changelist") + f"?group__id__exact={self.instance.pk}"
        shown = min(total, SECTION_LIMIT)
        footer = format_html(
            '<div class="f7-section-footer">Показано {} из {} по выручке · '
            '<a href="{}" class="f7-link">все артикулы группы →</a></div>',
            shown, total, url,
        )
        return mark_safe(html + footer)


@admin.register(ItemGroup)
class ItemGroupAdmin(AppModelAdmin):
    list_sections = [GroupItemsSection]
    list_per_page = 100

    list_display = ["group_col", "demand_col", "items_col", "revenue_col", "regular_col", "manual_col"]
    list_display_links = ["group_col"]
    list_filter = [("demand_type", ChoicesDropdownFilter)]
    search_fields = ["name", "code", "description"]
    ordering = ["sort", "name"]

    fieldsets = (
        (None, {"fields": [("name", "code"), ("demand_type", "sort"), "description"]}),
    )

    def get_queryset(self, request):
        total = float(Item.objects.aggregate(s=Sum("revenue"))["s"] or 0) or 1.0
        return super().get_queryset(request).annotate(
            revenue_total=Value(total, output_field=FloatField()),
            items_n=Count("items", distinct=True),
            revenue_sum=Sum("items__revenue"),
            regular_n=Count("items", filter=Q(items__months__gte=Item.REGULAR_MONTHS), distinct=True),
            manual_n=Count("items", filter=Q(items__group_source=GroupSource.MANUAL), distinct=True),
        )

    def get_readonly_fields(self, request, obj=None):
        # код связывает группу с правилами разметки — после создания не меняем
        return ["code"] if obj else []

    # --- колонки
    @display(description="Группа", ordering="name")
    def group_col(self, obj):
        return FirstCol(obj.name, obj.code).name_subtext

    @display(description="Тип спроса", ordering="demand_type")
    def demand_col(self, obj):
        return demand_badge(obj.demand_type)

    @display(description="Артикулов", ordering="items_n")
    def items_col(self, obj):
        return num_cell(f"{obj.items_n:,}".replace(",", " "))

    @display(description="Выручка, ₽", ordering="revenue_sum")
    def revenue_col(self, obj):
        share = 100 * float(obj.revenue_sum or 0) / obj.revenue_total
        return num_cell(money(obj.revenue_sum), f"{share:.1f}% выручки")

    @display(description="Регулярных", ordering="regular_n")
    def regular_col(self, obj):
        return num_cell(str(obj.regular_n), f"{Item.REGULAR_MONTHS}+ мес.")

    @display(description="Вручную", ordering="manual_n")
    def manual_col(self, obj):
        return num_cell(str(obj.manual_n)) if obj.manual_n else num_cell("—")
