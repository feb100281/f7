"""
Пересчёт витрин: SQL из sql/marts/ по порядку (MARTS), затем статистика
в карточках артикулов (catalog_item) из mart_item_stats.
"""

from __future__ import annotations

import time
from decimal import Decimal

from django.db import transaction

from core.services.duck import Duck

# Порядок важен: _base.sql создаёт временное представление lines для остальных,
# item_stats читает item_month, _meta.sql — отметка о пересчёте, всегда последним.
MARTS = [
    "marts/_base.sql",
    "marts/sales_month.sql",
    "marts/group_month.sql",
    "marts/service_month.sql",
    "marts/service_items.sql",
    "marts/season.sql",
    "marts/item_month.sql",
    "marts/item_stats.sql",
    "marts/_meta.sql",
]


def build_marts(log=None) -> list[tuple[str, float]]:
    done = []
    with Duck() as duck:
        for name in MARTS:
            t = time.monotonic()
            duck.run(name)
            done.append((name, time.monotonic() - t))
            if log:
                log(f"   {name} — {done[-1][1]:.1f} c")
    return done


def _dec(value, places: int) -> Decimal:
    return Decimal(str(round(float(value or 0), places)))


def refresh_item_stats() -> int:
    """Скопировать статистику из витрины в поля карточки артикула (для списков и фильтров админки)."""
    from catalog.models import Item
    from marts.models import MartItemStats

    stats = {s.item_id: s for s in MartItemStats.objects.all()}
    items = list(Item.objects.only("id", "first_sale", "last_sale", "qty", "revenue", "cost", "docs", "months"))
    for item in items:
        s = stats.get(item.id)
        item.first_sale = s.first_sale if s else None
        item.last_sale = s.last_sale if s else None
        item.qty = _dec(s.qty if s else 0, 3)
        item.revenue = _dec(s.revenue if s else 0, 2)
        item.cost = _dec(s.cost if s else 0, 2)
        item.docs = int(s.docs) if s else 0
        item.months = int(s.months) if s else 0
    with transaction.atomic():
        Item.objects.bulk_update(
            items, ["first_sale", "last_sale", "qty", "revenue", "cost", "docs", "months"], batch_size=1000,
        )
    return len(stats)
