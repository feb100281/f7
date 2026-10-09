"""
Прогноз вперёд: по каждому ряду — Prophet с параметрами последнего подбора (или по умолчанию),
обучение на всей истории до последней даты факта, прогноз до конца месяца + `horizon` месяцев.

Помесячный коридор считается по выборкам Prophet (predictive_samples): выборки по дням
складываются в месяцы, границы — 10-й и 90-й процентили. «Всего» — сумма выборок двух рядов.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from django.db import transaction

from forecast.models import MODEL_SERIES, ForecastPoint, ForecastRun, Series, TuneRun

from . import engine
from .data import load_daily

SAMPLES = 500


def best_params(series: str) -> tuple[dict, int | None]:
    run = TuneRun.objects.filter(series=series).first()
    if run and run.best:
        return run.best, run.pk
    return dict(engine.DEFAULT_PARAMS), None


def build(horizon: int = 6, note: str = "", log=print) -> ForecastRun:
    started = time.time()
    engine.quiet()
    daily_all, data_end = load_daily()
    cutoff = data_end + pd.Timedelta(days=1)
    first_month = engine.month_start(data_end) if cutoff.day != 1 else cutoff
    end = engine.add_months(first_month, horizon + (1 if cutoff.day != 1 else 0))
    log(f"   факт по {data_end:%d.%m.%Y}, прогноз {cutoff:%d.%m.%Y} – {end - pd.Timedelta(days=1):%d.%m.%Y}")

    params, tune_runs, draws, before = {}, {}, {}, {}
    for series in MODEL_SERIES:
        p, run_id = best_params(series)
        params[series], tune_runs[series] = p, run_id
        log(f"   {Series(series).label}: {engine.params_label(p)}" + ("" if run_id else " (подбора не было — по умолчанию)"))
        days, _, d = engine.fit_predict(daily_all[series], p, cutoff, end, samples=SAMPLES)
        draws[series] = engine.monthly(days, d)
        # факт месяца, в котором кончаются данные (для ожидания по месяцу)
        before[series] = float(engine.actual_monthly(daily_all[series], first_month, cutoff).sum())

    draws[Series.TOTAL] = sum(draws[s] for s in MODEL_SERIES)
    before[Series.TOTAL] = sum(before[s] for s in MODEL_SERIES)

    rows = []
    for series, m in draws.items():
        arr = m.to_numpy()
        lo = np.percentile(arr, engine.INTERVAL[0], axis=1)
        hi = np.percentile(arr, engine.INTERVAL[1], axis=1)
        mean = arr.mean(axis=1)
        for i, month in enumerate(m.index):
            rows.append(dict(
                series=str(series), month=month.date(), yhat=float(mean[i]),
                lower=float(lo[i]), upper=float(hi[i]),
                actual_before=before[series] if month == first_month else 0.0,
            ))

    with transaction.atomic():
        run = ForecastRun.objects.create(
            data_end=data_end.date(), horizon=horizon, params={str(k): v for k, v in params.items()},
            tune_runs={str(k): v for k, v in tune_runs.items()}, note=note,
            seconds=round(time.time() - started, 1),
        )
        ForecastPoint.objects.bulk_create([ForecastPoint(run=run, **r) for r in rows])

    total = [r for r in rows if r["series"] == Series.TOTAL]
    log("   всего по месяцам, млн ₽: " + ", ".join(
        f"{pd.Timestamp(r['month']):%m.%y} {(r['yhat'] + r['actual_before']) / 1e6:.1f}" for r in total))
    return run
