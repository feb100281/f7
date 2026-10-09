"""Общие кусочки админок номенклатуры: форматирование и бэйджи."""

from __future__ import annotations

from django.utils.html import format_html

from catalog.models import DemandType, GroupSource
from core.admins import Badge

DEMAND_BADGES = {
    DemandType.CONSUMABLE: ("water_drop", "primary"),
    DemandType.WEAR: ("autorenew", "warning"),
    DemandType.REPAIR: ("build", "info"),
    DemandType.BODY: ("directions_car", "gray"),
    DemandType.ACCESSORY: ("shopping_bag", "success"),
    DemandType.FASTENER: ("hardware", "gray"),
    DemandType.OTHER: ("help", "gray"),
}

SOURCE_BADGES = {
    # источник: (короткая подпись, иконка, стиль)
    GroupSource.RULE: ("Правило", "rule", "gray"),
    GroupSource.ARTICLE: ("Артикул", "tag", "gray"),
    GroupSource.MANUAL: ("Вручную", "person", "primary"),
    GroupSource.NONE: ("Нет", "help", "danger"),
}


def money(value) -> str:
    """1234567.8 → «1 234 568» (без копеек, тонкий пробел между разрядами)."""
    if value in (None, ""):
        return "—"
    return f"{float(value):,.0f}".replace(",", " ")


def qty(value) -> str:
    if value in (None, ""):
        return "—"
    v = float(value)
    return f"{v:,.0f}".replace(",", " ") if v == int(v) else f"{v:,.2f}".replace(",", " ")


def demand_badge(demand_type: str | None):
    if not demand_type:
        return Badge(None).badge
    icon, style = DEMAND_BADGES.get(demand_type, ("help", "gray"))
    return Badge(DemandType(demand_type).label, icon, style).badge


def source_badge(item):
    """Короткий бэйдж «чем определена группа»; полное название и правило — во всплывающей подсказке."""
    label, icon, style = SOURCE_BADGES.get(item.group_source, ("—", "help", "gray"))
    title = item.get_group_source_display()
    if item.group_rule:
        title += f": {item.group_rule}"
    return Badge(label, icon, style, title=title).badge


def num_cell(value: str, sub: str | None = None):
    """Число справа + подпись мелко под ним."""
    if sub:
        return format_html('<span class="f7-num">{}<span class="f7-field-sub">{}</span></span>', value, sub)
    return format_html('<span class="f7-num">{}</span>', value)
