"""
Начальные справочники: товарные группы и техника из catalog/rules.py.

Создаются только недостающие записи — названия, тип спроса и порядок,
которые менеджеры поправили в админке, не перезаписываются.
"""

from __future__ import annotations

from catalog import rules as R
from catalog.models import ItemGroup, Platform


def ensure_groups() -> int:
    created = 0
    for i, (code, (name, demand)) in enumerate(R.GROUPS.items(), start=1):
        _, new = ItemGroup.objects.get_or_create(
            code=code,
            defaults={"name": name, "demand_type": demand, "sort": i * 10},
        )
        created += new
    return created


def ensure_platforms() -> int:
    created = 0
    for i, (code, name) in enumerate(R.PLATFORMS.items(), start=1):
        _, new = Platform.objects.get_or_create(code=code, defaults={"name": name, "sort": i * 10})
        created += new
    return created
