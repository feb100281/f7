from django.contrib import admin
from django.db.models import Count
from unfold.decorators import display

from catalog.models import Platform
from core.admins import AppModelAdmin


@admin.register(Platform)
class PlatformAdmin(AppModelAdmin):
    list_display = ["name", "code", "items_col", "sort"]
    list_editable = ["sort"]
    search_fields = ["name", "code"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(items_n=Count("items"))

    def get_readonly_fields(self, request, obj=None):
        return ["code"] if obj else []

    @display(description="Артикулов", ordering="items_n")
    def items_col(self, obj):
        return obj.items_n
