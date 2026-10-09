from django.contrib import admin
from django.db.models import Count, Max, Min, Q, Sum
from unfold.decorators import display

from core.admins import AppModelAdmin, FirstCol
from sales.models import Department, DocKind

from .common import money, num_cell


@admin.register(Department)
class DepartmentAdmin(AppModelAdmin):
    list_display = ["dept_col", "city", "is_active", "docs_col", "service_col", "revenue_col", "period_col"]
    list_display_links = ["dept_col"]
    list_filter = ["is_active", "city"]
    search_fields = ["prefix", "name", "city"]
    fields = [("prefix", "name"), ("city", "is_active"), "note"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            docs_n=Count("docs", distinct=True),
            service_n=Count("docs", filter=Q(docs__kind=DocKind.SERVICE), distinct=True),
            revenue_sum=Sum("docs__lines__revenue"),
            first=Min("docs__date"),
            last=Max("docs__date"),
        )

    def get_readonly_fields(self, request, obj=None):
        return ["prefix"] if obj else []

    @display(description="Подразделение", ordering="prefix")
    def dept_col(self, obj):
        return FirstCol(obj.name or "— название не задано", obj.prefix).name_subtext

    @display(description="Документов", ordering="docs_n")
    def docs_col(self, obj):
        return num_cell(f"{obj.docs_n:,}".replace(",", " "))

    @display(description="Нарядов", ordering="service_n")
    def service_col(self, obj):
        return num_cell(f"{obj.service_n:,}".replace(",", " "))

    @display(description="Выручка, ₽", ordering="revenue_sum")
    def revenue_col(self, obj):
        return num_cell(money(obj.revenue_sum))

    @display(description="Период")
    def period_col(self, obj):
        if not obj.first:
            return "—"
        return f"{obj.first:%m.%Y} – {obj.last:%m.%Y}"
