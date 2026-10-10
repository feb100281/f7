"""
Проверка штук на прошлом: «как сейчас» (каждый номер отдельно) против «со склейкой номеров».

С каждой прошлой отсечки берём прогноз выручки, который модель тогда сделала (проверка на
прошлом — BacktestPoint последних подборов сервиса и продаж), раскладываем его лестницей
по данным, известным на ту дату, и сравниваем штуки за `months` месяцев с фактом:

    ошибка = Σ |прогноз − факт| по артикулам / Σ факт

«Как сейчас» сравнивается с фактом каждого номера, «со склейкой» — с фактом семейства на
актуальном номере (заказывают актуальный номер — он и закрывает спрос всего семейства).
Отдельно — только по артикулам с заменами: там разница и видна.

Лестница пишет витрины mart_fc_* — после проверки раскладка текущего прогноза пересобирается.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pandas as pd
from django.db import transaction
from django.db.models import Count

from catalog.models import Item
from core.services.duck import Duck
from forecast.models import BacktestPoint, ForecastRun, QtyCheck, QtyCheckPoint, QtyCheckVariant, Series, TuneRun
from forecast.services.ladder import compute, ladder


def _family_ids() -> set[int]:
    members = set(Item.objects.exclude(family_head=None).values_list("id", flat=True))
    heads = set(Item.objects.exclude(family_head=None).values_list("family_head_id", flat=True))
    return members | heads


def _cutoffs(tune: dict, months: int) -> list:
    """Отсечки, где у обоих рядов есть прогноз и факт на все `months` месяцев."""
    sets = []
    for run in tune.values():
        rows = (BacktestPoint.objects.filter(run=run, h__lte=months).values("cutoff")
                .annotate(n=Count("id")).filter(n=months))
        sets.append({r["cutoff"] for r in rows})
    return sorted(set.intersection(*sets)) if sets else []


def qty_check(months: int = 6, log=print) -> QtyCheck:
    started = time.time()
    tune = {s: TuneRun.objects.filter(series=s).first() for s in (Series.SERVICE, Series.SHOP)}
    missing = [Series(s).label for s, r in tune.items() if r is None]
    if missing:
        raise ValueError(f"Нет подбора параметров для: {', '.join(missing)} — сначала «Прогноз: подбор параметров».")
    cutoffs = _cutoffs(tune, months)
    if not cutoffs:
        raise ValueError(f"В проверке на прошлом нет отсечек с фактом на {months} мес.")
    fam_ids = _family_ids()
    log(f"   отсечек: {len(cutoffs)} ({cutoffs[0]:%m.%Y} – {cutoffs[-1]:%m.%Y}), "
        f"артикулов с заменами: {len(fam_ids)}")

    points = []
    with Duck() as duck:
        for cutoff in cutoffs:
            for variant in (QtyCheckVariant.ITEMS, QtyCheckVariant.FAMILIES):
                fam = variant == QtyCheckVariant.FAMILIES
                params = dict(data_end=cutoff - timedelta(days=1), families=fam, cutoff=cutoff, months=months,
                              tune_service=tune[Series.SERVICE].pk, tune_shop=tune[Series.SHOP].pk)
                _, items = compute(duck, "forecast/ladder_input_backtest.sql", **params)
                fc = (items.groupby("item_id").qty.sum() if len(items) else pd.Series(dtype=float)).rename("f")
                fact = duck.df("forecast/qty_actual.sql")
                act = (fact.set_index("item_id").qty if len(fact) else pd.Series(dtype=float)).rename("a")
                df = pd.concat([fc, act], axis=1).fillna(0.0)
                df.index = df.index.astype(int)
                df["e"] = (df.f - df.a).abs()
                in_fam = df[df.index.isin(fam_ids)]
                points.append(QtyCheckPoint(
                    cutoff=cutoff, variant=variant, items=int((df.a > 0).sum()),
                    actual=float(df.a.sum()), forecast=float(df.f.sum()), abs_err=float(df.e.sum()),
                    fam_actual=float(in_fam.a.sum()), fam_forecast=float(in_fam.f.sum()),
                    fam_abs_err=float(in_fam.e.sum()),
                ))
            a, b = points[-2], points[-1]
            log(f"   {cutoff:%m.%Y}: факт {a.actual:,.0f} шт.; ошибка как сейчас {a.abs_err / a.actual:.1%}, "
                f"со склейкой {b.abs_err / b.actual:.1%}; по семействам {a.fam_abs_err / max(a.fam_actual, 1):.1%} → "
                f"{b.fam_abs_err / max(b.fam_actual, 1):.1%}".replace(",", " "))

    with transaction.atomic():
        check = QtyCheck.objects.create(
            data_end=max(r.data_end for r in tune.values()), months=months,
            tune_runs={s: r.pk for s, r in tune.items()}, seconds=round(time.time() - started, 1),
        )
        for p in points:
            p.run = check
        QtyCheckPoint.objects.bulk_create(points)

    # витрины mart_fc_* сейчас от последней отсечки — пересобрать раскладку текущего прогноза
    run = ForecastRun.objects.first()
    if run:
        log(f"   раскладка текущего прогноза пересобирается ({run})")
        ladder(run, log=log)  # как обычно — по семействам (USE_FAMILIES)
    return check


def summary(check: QtyCheck) -> dict | None:
    """Итог для страницы: ошибка по вариантам (всё / только семейства) и по отсечкам."""
    pts = list(check.points.all())
    if not pts:
        return None
    by = {v: [p for p in pts if p.variant == v] for v in QtyCheckVariant.values}

    def agg(rows, fam=False):
        act = sum(p.fam_actual if fam else p.actual for p in rows)
        err = sum(p.fam_abs_err if fam else p.abs_err for p in rows)
        fc = sum(p.fam_forecast if fam else p.forecast for p in rows)
        return {"actual": act, "forecast": fc, "err": err / act if act else None,
                "bias": (fc - act) / act if act else None}

    variants = [{"key": v, "label": QtyCheckVariant(v).label, "all": agg(by[v]), "fam": agg(by[v], True)}
                for v in QtyCheckVariant.values]
    cut = sorted({p.cutoff for p in pts})
    rows = []
    for c in cut:
        r = {"cutoff": c}
        for v in QtyCheckVariant.values:
            p = next((p for p in by[v] if p.cutoff == c), None)
            r[v] = {"err": p.abs_err / p.actual if p and p.actual else None,
                    "fam": p.fam_abs_err / p.fam_actual if p and p.fam_actual else None}
        rows.append(r)
    items, fams = variants
    gain = (items["fam"]["err"] - fams["fam"]["err"]) if items["fam"]["err"] is not None and fams["fam"]["err"] is not None else None
    return {"check": check, "variants": variants, "rows": rows, "gain_fam": gain,
            "gain_all": (items["all"]["err"] - fams["all"]["err"]) if items["all"]["err"] is not None else None}
