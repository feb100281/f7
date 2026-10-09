"""
Подбор параметров Prophet: перебор сетки × rolling-бэктест.

Каждая комбинация параметров прогнозирует с нескольких отсечек в прошлом на `horizon`
месяцев вперёд; ошибка (WAPE по месяцам) усредняется по всем отсечкам — так модель
проверяется и на пиках, и на спадах. Победитель — минимум средней ошибки на 1–3 месяцах
и на всём горизонте. Его прогнозы с коридором сохраняются для дашборда «Проверка на прошлом».
"""

from __future__ import annotations

import itertools
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor

from django.db import transaction

from forecast.models import BacktestPoint, TuneResult, TuneRun

from . import engine
from .data import load_daily


def expand(grid: dict) -> list[dict]:
    keys = list(engine.DEFAULT_GRID)
    values = [grid.get(k, engine.DEFAULT_GRID[k]) for k in keys]
    combos = [dict(zip(keys, v)) for v in itertools.product(*values)]
    if engine.DEFAULT_PARAMS not in combos:  # «Prophet как есть» — всегда для сравнения
        combos.append(dict(engine.DEFAULT_PARAMS))
    return combos


def _run_all(daily, combos, cutoffs, horizon, workers, log):
    jobs = [(i, daily, p, cutoffs, horizon) for i, p in enumerate(combos)]
    results, step, done = [None] * len(jobs), max(1, len(jobs) // 10), 0

    def collect(i, res):
        nonlocal done
        results[i] = res
        done += 1
        if done % step == 0 or done == len(jobs):
            log(f"   {done}/{len(jobs)}")

    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for i, res in pool.map(engine.evaluate_job, jobs, chunksize=max(1, len(jobs) // (workers * 8))):
                collect(i, res)
    else:
        for job in jobs:
            collect(*engine.evaluate_job(job))
    return results


def tune(series: str, grid: dict | None = None, horizon: int = 6, step: int = 2,
         min_train_days: int = 730, workers: int = 0, log=print) -> TuneRun:
    started = time.time()
    daily_all, data_end = load_daily()
    daily = daily_all[series]

    grid = grid or engine.DEFAULT_GRID
    combos = expand(grid)
    windows = sorted({c["window"] for c in combos}, key=str)
    cutoffs = engine.make_cutoffs(daily, windows, horizon, step, min_train_days)
    if len(cutoffs) < 2:
        raise ValueError(
            f"Мало данных для проверки: отсечек {len(cutoffs)}. Уменьшите min_train_days, "
            "horizon или уберите из сетки поздние окна обучения."
        )
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    log(f"   данные по {data_end:%d.%m.%Y}; отсечки: {', '.join(f'{c:%m.%Y}' for c in cutoffs)}")
    log(f"   комбинаций: {len(combos)}, обучений: {len(combos) * len(cutoffs)}, процессов: {workers}")

    raw = _run_all(daily, combos, [c.date() for c in cutoffs], horizon, workers, log)

    scored, failed = [], []
    for params, res in zip(combos, raw):
        if isinstance(res, str):
            failed.append((params, res))
            continue
        s = engine.score(res, horizon)
        if not math.isnan(s["score"]):
            scored.append((params, s))
    if failed:
        log(f"   не посчиталось комбинаций: {len(failed)}; пример: {failed[0][1]}")
    if not scored:
        raise RuntimeError("Ни одна комбинация не посчиталась — см. ошибку выше.")

    scored.sort(key=lambda x: x[1]["score"])
    best_params, best = scored[0]
    default = next((s for p, s in scored if p == engine.DEFAULT_PARAMS), None)

    log("   лучшая модель: " + engine.params_label(best_params))
    log(f"   ошибка 1–3 мес.: {best['wape3']:.1%}, на {horizon} мес.: {best['wape6']:.1%}, смещение {best['bias']:+.1%}")
    if default:
        log(f"   Prophet по умолчанию: {default['wape3']:.1%} / {default['wape6']:.1%}")

    log("   прогнозы лучшей модели с коридором")
    points = engine.evaluate(daily, best_params, [c.date() for c in cutoffs], horizon, samples=300)

    with transaction.atomic():
        run = TuneRun.objects.create(
            series=series, data_end=data_end.date(), horizon=horizon,
            cutoffs=[str(c.date()) for c in cutoffs], combos=len(combos),
            seconds=round(time.time() - started, 1), best=best_params,
            wape3=best["wape3"], wape6=best["wape6"], bias=best["bias"],
            default_wape3=default["wape3"] if default else None,
            default_wape6=default["wape6"] if default else None,
        )
        TuneResult.objects.bulk_create([
            TuneResult(run=run, rank=rank, params=p, wape3=s["wape3"], wape6=s["wape6"], bias=s["bias"],
                       score=s["score"], folds=s["folds"], is_default=(p == engine.DEFAULT_PARAMS))
            for rank, (p, s) in enumerate(scored, start=1)
        ])
        BacktestPoint.objects.bulk_create([BacktestPoint(run=run, **row) for row in points])
    return run
