from __future__ import annotations

from catalog.admin.common import money, num_cell, qty  # noqa: F401 — общий формат чисел
from core.admins import Badge
from sales.models import DocKind

KIND_BADGES = {
    DocKind.SERVICE: ("build", "primary"),
    DocKind.SALE: ("receipt_long", "info"),
    DocKind.RETAIL: ("storefront", "success"),
    DocKind.RETURN: ("undo", "warning"),
    DocKind.CORRECTION: ("edit_note", "gray"),
    DocKind.OTHER: ("help", "gray"),
}


def kind_badge(kind: str | None):
    if not kind:
        return Badge(None).badge
    icon, style = KIND_BADGES.get(kind, ("help", "gray"))
    return Badge(DocKind(kind).label, icon, style).badge


class ReadOnlyAdminMixin:
    """Данные продаж приходят только из импорта — руками не добавляем и не правим."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
