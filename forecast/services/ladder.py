"""
Лестница: прогноз выручки (ForecastRun) → товарные группы → артикулы → штуки.

Расчёт — в DuckDB (sql/forecast/ladder.sql), здесь только запуск и запись результата
в ForecastGroup / ForecastItem. Предыдущая раскладка того же прогноза заменяется.
"""

from __future__ import annotations

import time

from django.db import transaction

from core.services.duck import Duck
from forecast.models import ForecastGroup, ForecastItem, ForecastRun


def _none(v):
    return None if v is None or v != v else v  # NaN → None


def _id(v):
    v = _none(v)
    return int(v) if v is not None else None


def ladder(run: ForecastRun, log=print) -> dict:
    started = time.time()
    with Duck() as duck:
        duck.params(run_id=run.pk, data_end=run.data_end)
        duck.run("forecast/ladder.sql")
        groups = duck.df("forecast/ladder_groups.sql")
        items = duck.df("forecast/ladder_items.sql")

    qty_by_group = items.groupby(["series", "month", items.group_id.fillna(-1)]).qty.sum().to_dict() if len(items) else {}

    with transaction.atomic():
        ForecastItem.objects.filter(run=run).delete()
        ForecastGroup.objects.filter(run=run).delete()
        ForecastGroup.objects.bulk_create([
            ForecastGroup(
                run=run, series=r.series, group_id=_id(r.group_id), month=r.month,
                share=float(r.share), revenue=float(r.revenue),
                qty=float(qty_by_group.get((r.series, r.month, _id(r.group_id) or -1), 0.0)),
            )
            for r in groups.itertuples()
        ], batch_size=2000)
        ForecastItem.objects.bulk_create([
            ForecastItem(
                run=run, series=r.series, item_id=int(r.item_id), group_id=_id(r.group_id), month=r.month,
                qty=float(r.qty), revenue=float(_none(r.revenue) or 0), price=_none(r.price),
                price_source=r.price_source,
            )
            for r in items.itertuples()
        ], batch_size=5000)

    result = {
        "groups": len(groups), "items": int(items.item_id.nunique()) if len(items) else 0,
        "rows": len(items), "qty": float(items.qty.sum()) if len(items) else 0.0,
        "seconds": round(time.time() - started, 1),
    }
    n = lambda v: f"{v:,.0f}".replace(",", " ")  # noqa: E731
    log(f"   групп × месяцев: {n(result['groups'])}, артикулов: {n(result['items'])}, строк: {n(result['rows'])}, "
        f"штук всего: {n(result['qty'])}")
    return result
