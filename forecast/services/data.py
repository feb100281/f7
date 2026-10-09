"""Данные для прогноза: документы из базы (sql/forecast/docs.sql) → дневные ряды."""

from __future__ import annotations

import pandas as pd

from core.services.duck import Duck


def load_daily() -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    """→ ({ряд: DataFrame ds, y, maxdoc — каждый день без пропусков}, последняя дата факта).

    y — выручка дня (0, если продаж не было), maxdoc — самый крупный документ дня
    (по нему отсекаются выбросы). Все ряды на общем календаре: от первой до последней
    даты данных в целом.
    """
    with Duck() as duck:
        docs = duck.df("forecast/docs.sql")
    if docs is None or docs.empty:
        raise ValueError("Нет продаж в базе — сначала «Импорт продаж из 1С».")

    docs["date"] = pd.to_datetime(docs["date"])
    docs["revenue"] = docs["revenue"].astype(float)
    calendar = pd.date_range(docs.date.min(), docs.date.max(), freq="D")

    out = {}
    for series, g in docs.groupby("series"):
        day = g.groupby("date").agg(y=("revenue", "sum"), maxdoc=("revenue", "max"))
        day = day.reindex(calendar, fill_value=0.0)
        day.index.name = "ds"
        out[series] = day.reset_index()
    return out, docs.date.max()
