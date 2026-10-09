"""
Загрузка продаж в базу: документы и строки со ссылкой на номенклатуру.

Пока выгрузки — целые сезоны, загрузка полная: таблицы продаж очищаются
и заливаются заново (≈ 30 тыс. документов, 85 тыс. строк — секунды).
Подразделения создаются по префиксам номеров, их названия не трогаются.
Артикулы, которых ещё нет в номенклатуре, создаются с группой по правилам.
"""

from __future__ import annotations

import math
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone

from catalog.models import Item
from catalog.services.classify import Classifier
from sales.models import Department, SalesDoc, SalesLine

BATCH = 2000


def _dec(value, places: int, null: bool = False):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None if null else Decimal(0)
    try:
        import pandas as pd
        if pd.isna(value):
            return None if null else Decimal(0)
    except (TypeError, ValueError):
        pass
    return Decimal(str(round(float(value), places)))


def _aware(dt):
    """Время из 1С — местное (TIME_ZONE проекта), без зоны."""
    dt = dt.to_pydatetime() if hasattr(dt, "to_pydatetime") else dt
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _truncate():
    """Быстрая очистка без загрузки объектов в память (строки → документы)."""
    with connection.cursor() as cur:
        cur.execute(f'DELETE FROM "{SalesLine._meta.db_table}"')
        cur.execute(f'DELETE FROM "{SalesDoc._meta.db_table}"')


def _ensure_items(lines_df) -> int:
    """Артикулы из продаж, которых нет в номенклатуре, — создать с группой по правилам."""
    known = set(Item.objects.values_list("article", flat=True))
    missing = (
        lines_df[~lines_df["article"].isin(known)]
        .sort_values("doc_dt")
        .groupby("article")["name"].last()
    )
    if missing.empty:
        return 0
    classify = Classifier()
    new = []
    for article, name in missing.items():
        v = classify(name, article)
        new.append(Item(
            article=article, name=str(name or article)[:255],
            group_id=v.group_id, group_source=v.group_source, group_rule=v.group_rule, platform_id=v.platform_id,
        ))
    Item.objects.bulk_create(new, batch_size=BATCH)
    return len(new)


def load_sales(lines_df, docs_df) -> dict:
    with transaction.atomic():
        new_items = _ensure_items(lines_df)

        # --- подразделения
        prefixes = sorted({p for p in docs_df["doc_prefix"].dropna().astype(str) if p})
        existing = set(Department.objects.values_list("prefix", flat=True))
        Department.objects.bulk_create([Department(prefix=p) for p in prefixes if p not in existing])
        dept = dict(Department.objects.values_list("prefix", "id"))

        _truncate()

        # --- документы
        docs = [
            SalesDoc(
                kind=row.doc_kind,
                doc_type=row.doc_type,
                number=row.doc_number,
                dt=_aware(row.doc_dt),
                date=row.doc_dt.date(),
                department_id=dept.get(str(row.doc_prefix)) if row.doc_prefix else None,
            )
            for row in docs_df.itertuples(index=False)
        ]
        SalesDoc.objects.bulk_create(docs, batch_size=BATCH)
        doc_id = {(d.doc_type, d.number, d.dt): d.pk for d in docs}

        # --- строки
        item_id = dict(Item.objects.values_list("article", "id"))
        lines, skipped = [], 0
        for row in lines_df.itertuples(index=False):
            pk = doc_id.get((row.doc_type, row.doc_number, _aware(row.doc_dt)))
            if pk is None:
                skipped += 1
                continue
            lines.append(SalesLine(
                doc_id=pk,
                item_id=item_id[row.article],
                qty=_dec(row.qty, 3),
                revenue=_dec(row.revenue, 2, null=True),
                cost=_dec(row.cost, 2, null=True),
            ))
        SalesLine.objects.bulk_create(lines, batch_size=BATCH)

    return {
        "docs": len(docs),
        "lines": len(lines),
        "skipped": skipped,
        "departments": len(prefixes),
        "new_items": new_items,
    }
