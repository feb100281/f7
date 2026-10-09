"""
Номенклатура из разобранных строк продаж (catalog.Item).

    • новый артикул  → создаётся, группа и техника — по правилам;
    • существующий   → обновляется название (последнее по дате) и группа по правилам,
                        если её не меняли руками;
    • ручная разметка (group_source = manual) не трогается;
    • статистика продаж (выручка, месяцы…) — не здесь: после загрузки продаж
      её пересчитывает витрина mart_item_stats (marts.services.build.refresh_item_stats).
Артикулы, которых нет в выгрузке, не удаляются.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from catalog.models import GroupSource, Item

from .classify import Classifier

NAME_FIELDS = ["name", "name_1c", "updated"]
GROUP_FIELDS = ["group", "group_source", "group_rule", "platform"]


def _str(value, size: int) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()[:size]


def sync_items(lines_df) -> dict:
    latest = (
        lines_df.sort_values("doc_dt")
        .groupby("article", as_index=False)
        .agg(name=("name", "last"), name_1c=("name_1c", "last"))
    )

    classify = Classifier()
    existing = dict(Item.objects.values_list("article", "group_source"))

    now = timezone.now()
    to_create, auto_update, manual_update = [], [], []
    for row in latest.itertuples(index=False):
        article = str(row.article).strip()
        if not article:
            continue
        name = _str(row.name, 255) or article
        item = Item(article=article, name=name, name_1c=_str(row.name_1c, 255), updated=now)
        source = existing.get(article)
        if source == GroupSource.MANUAL:
            manual_update.append(item)
            continue
        v = classify(name, article)
        item.group_id, item.group_source = v.group_id, v.group_source
        item.group_rule, item.platform_id = v.group_rule, v.platform_id
        (auto_update if source is not None else to_create).append(item)

    with transaction.atomic():
        Item.objects.bulk_create(to_create, batch_size=1000)
        Item.objects.bulk_create(
            auto_update, batch_size=1000,
            update_conflicts=True, unique_fields=["article"], update_fields=NAME_FIELDS + GROUP_FIELDS,
        )
        Item.objects.bulk_create(
            manual_update, batch_size=1000,
            update_conflicts=True, unique_fields=["article"], update_fields=NAME_FIELDS,
        )

    return {
        "rows": len(latest),
        "created": len(to_create),
        "updated": len(auto_update),
        "manual_kept": len(manual_update),
        "unclassified": Item.objects.filter(group_source=GroupSource.NONE).count(),
    }
