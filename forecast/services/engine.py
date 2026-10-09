"""
Ядро прогноза: Prophet на дневной (или недельной) выручке → помесячные суммы.

Модуль без Django — его функции выполняются и в параллельных процессах подбора.

Параметры модели (dict):
    window   — окно обучения: "all" | "2023-01-01" (с даты) | "3y" / "2y" (последние N лет до отсечки)
    outlier  — порог выбросов, ₽: дни с документом крупнее порога не участвуют в обучении
               (Prophet их пропускает, рецепт из документации); None — без чистки
    cps      — changepoint_prior_scale: гибкость тренда
    sps      — seasonality_prior_scale: сила сезонности
    mode     — "additive" | "multiplicative": сезонность прибавляется к тренду или умножается
    freq     — "D" — учимся по дням (недельная сезонность + праздники РФ),
               "W" — по полным неделям (ряд глаже, меньше шума)
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

DEFAULT_PARAMS = {"window": "all", "outlier": None, "cps": 0.05, "sps": 10.0, "mode": "additive", "freq": "D"}

DEFAULT_GRID = {
    "window": ["all", "2023-01-01", "3y", "2y"],
    "outlier": [None, 1_000_000, 3_000_000],
    "cps": [0.01, 0.05, 0.2],
    "sps": [0.1, 1.0, 10.0],
    "mode": ["additive", "multiplicative"],
    "freq": ["D", "W"],
}

INTERVAL = (10, 90)  # коридор прогноза: 80% (как interval_width у Prophet по умолчанию)


def quiet():
    for name in ("cmdstanpy", "prophet", "prophet.plot"):
        logging.getLogger(name).setLevel(logging.ERROR)


def month_start(d) -> pd.Timestamp:
    d = pd.Timestamp(d)
    return pd.Timestamp(d.year, d.month, 1)


def add_months(d, n: int) -> pd.Timestamp:
    return month_start(d) + pd.DateOffset(months=n)


def params_label(p: dict) -> str:
    w = str(p.get("window") or "all")
    if w == "all":
        window = "вся история"
    elif w.endswith("y"):
        window = f"последние {w[:-1]} г."
    else:
        window = f"с {pd.Timestamp(w):%d.%m.%Y}"
    outlier = "без чистки" if not p.get("outlier") else f"выбросы > {p['outlier'] / 1e6:g} млн"
    freq = "по дням" if p["freq"] == "D" else "по неделям"
    mode = "сложение" if p["mode"] == "additive" else "умножение"
    return f"{window} · {outlier} · {freq} · тренд {p['cps']:g} · сезонность {p['sps']:g} · {mode}"


# ---------------------------------------------------------------------------
# Данные для обучения
# ---------------------------------------------------------------------------

def train_start(window: str, cutoff: pd.Timestamp, data_start: pd.Timestamp) -> pd.Timestamp:
    if window in (None, "", "all"):
        return data_start
    if str(window).endswith("y"):
        return max(data_start, cutoff - pd.DateOffset(years=int(window[:-1])))
    return max(data_start, pd.Timestamp(window))


def fixed_start(window: str, data_start: pd.Timestamp) -> pd.Timestamp:
    """Начало окна, не зависящее от отсечки (для скользящих окон — начало данных)."""
    if window in (None, "", "all") or str(window).endswith("y"):
        return data_start
    return max(data_start, pd.Timestamp(window))


def _monday(d: pd.Timestamp) -> pd.Timestamp:
    return d - pd.Timedelta(days=d.dayofweek)


def prepare(daily: pd.DataFrame, params: dict, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """daily: ds (каждый день), y (выручка), maxdoc (самый крупный документ дня).
    → ds, y для Prophet на [start, end): выбросы → NaN, при freq=W — полные недели."""
    df = daily[(daily.ds >= start) & (daily.ds < end)].copy()
    outlier = params.get("outlier")
    if outlier:
        df.loc[df.maxdoc > float(outlier), "y"] = np.nan
    if params["freq"] == "W":
        df["week"] = df.ds - pd.to_timedelta(df.ds.dt.dayofweek, unit="D")
        g = df.groupby("week").agg(y=("y", "sum"), days=("ds", "size"), gaps=("y", lambda s: s.isna().sum()))
        g.loc[g.gaps > 0, "y"] = np.nan          # неделя с выбросом выпадает целиком
        g = g[g.days == 7]                        # только полные недели
        df = g.reset_index().rename(columns={"week": "ds"})
    return df[["ds", "y"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Модель
# ---------------------------------------------------------------------------

def make_model(params: dict, samples: int = 0):
    from prophet import Prophet

    model = Prophet(
        growth="linear",
        yearly_seasonality=True,
        weekly_seasonality=params["freq"] == "D",
        daily_seasonality=False,
        seasonality_mode=params["mode"],
        changepoint_prior_scale=float(params["cps"]),
        seasonality_prior_scale=float(params["sps"]),
        uncertainty_samples=samples,
    )
    if params["freq"] == "D":
        model.add_country_holidays(country_name="RU")
    return model


def fit_predict(daily: pd.DataFrame, params: dict, cutoff, end, samples: int = 0):
    """Обучение на данных до cutoff, прогноз дней [cutoff, end).
    → (days, yhat по дням, выборки по дням (n_days × samples) или None). Отрицательное → 0."""
    cutoff, end = pd.Timestamp(cutoff), pd.Timestamp(end)
    data_start = daily.ds.min()
    train = prepare(daily, params, train_start(params["window"], cutoff, data_start), cutoff)

    model = make_model(params, samples)
    model.fit(train)

    days = pd.date_range(cutoff, end - pd.Timedelta(days=1), freq="D")
    if params["freq"] == "D":
        future = pd.DataFrame({"ds": days})
        pos = np.arange(len(days))
        scale = 1.0
    else:
        first = _monday(cutoff)
        future = pd.DataFrame({"ds": pd.date_range(first, days[-1], freq="7D")})
        pos = ((days - first).days // 7).to_numpy()   # неделя каждого дня
        scale = 1 / 7                                  # неделя → поровну на 7 дней

    yhat = model.predict(future)["yhat"].to_numpy()[pos] * scale
    draws = None
    if samples:
        draws = np.asarray(model.predictive_samples(future)["yhat"])[pos] * scale
        draws = np.clip(draws, 0, None)
    return days, np.clip(yhat, 0, None), draws


def monthly(days: pd.DatetimeIndex, values) -> pd.DataFrame:
    """Дневные значения (вектор или матрица дни × выборки) → суммы по месяцам."""
    index = days.to_period("M").to_timestamp()
    return pd.DataFrame(np.asarray(values), index=index).groupby(level=0).sum()


def actual_monthly(daily: pd.DataFrame, start, end) -> pd.Series:
    """Факт по месяцам на [start, end) — с выбросами, это реальная выручка."""
    d = daily[(daily.ds >= pd.Timestamp(start)) & (daily.ds < pd.Timestamp(end))]
    return d.groupby(d.ds.dt.to_period("M").dt.to_timestamp()).y.sum()


# ---------------------------------------------------------------------------
# Бэктест одной комбинации параметров
# ---------------------------------------------------------------------------

def make_cutoffs(daily: pd.DataFrame, windows: list, horizon: int, step: int, min_train_days: int) -> list:
    """Отсечки — начала месяцев. Последняя: после неё ровно `horizon` полных месяцев факта.
    Первая: у каждого окна из перебора до неё не меньше min_train_days данных. Шаг — step мес."""
    data_start, data_end = daily.ds.min(), daily.ds.max()
    next_day = data_end + pd.Timedelta(days=1)
    last_full = month_start(data_end) if next_day.day == 1 else add_months(data_end, -1)
    last_cutoff = add_months(last_full, -(horizon - 1))

    earliest = max(fixed_start(w, data_start) for w in windows) + pd.Timedelta(days=min_train_days)
    earliest = earliest if earliest.day == 1 else add_months(earliest, 1)

    out, c = [], last_cutoff
    while c >= earliest:
        out.append(c)
        c = add_months(c, -step)
    return sorted(out)


def evaluate(daily: pd.DataFrame, params: dict, cutoffs: list, horizon: int, samples: int = 0) -> list:
    """Прогноз с каждой отсечки на horizon месяцев против факта.
    → [{cutoff, month, h, actual, yhat[, lower, upper]}]."""
    quiet()
    rows = []
    for cutoff in cutoffs:
        cutoff = pd.Timestamp(cutoff)
        end = add_months(cutoff, horizon)
        days, yhat, draws = fit_predict(daily, params, cutoff, end, samples)
        fc = monthly(days, yhat)[0]
        fact = actual_monthly(daily, cutoff, end)
        lo = hi = None
        if draws is not None:
            m = monthly(days, draws)
            lo = pd.Series(np.percentile(m.to_numpy(), INTERVAL[0], axis=1), index=m.index)
            hi = pd.Series(np.percentile(m.to_numpy(), INTERVAL[1], axis=1), index=m.index)
        for h, month in enumerate(fc.index, start=1):
            row = {"cutoff": cutoff.date(), "month": month.date(), "h": h,
                   "actual": float(fact.get(month, 0.0)), "yhat": float(fc[month])}
            if lo is not None:
                row.update(lower=float(lo[month]), upper=float(hi[month]))
            rows.append(row)
    return rows


def evaluate_job(args):
    """Для пула процессов: (i, daily, params, cutoffs, horizon) → (i, rows | Exception-текст)."""
    i, daily, params, cutoffs, horizon = args
    try:
        return i, evaluate(daily, params, cutoffs, horizon)
    except Exception as exc:  # одна сломанная комбинация не должна валить весь подбор
        return i, f"{type(exc).__name__}: {exc}"


def score(rows: list, horizon: int) -> dict:
    """WAPE = Σ|факт − прогноз| / Σ факт по месяцам: на 1–3 мес. и на всём горизонте; смещение."""
    df = pd.DataFrame(rows)
    err = (df.actual - df.yhat).abs()

    def wape(mask):
        a = df.actual[mask].sum()
        return float(err[mask].sum() / a) if a else float("nan")

    short = df.h <= min(3, horizon)
    folds = [
        {"cutoff": str(c), "wape": float((g.actual - g.yhat).abs().sum() / g.actual.sum()) if g.actual.sum() else None,
         "actual": float(g.actual.sum()), "yhat": float(g.yhat.sum())}
        for c, g in df.groupby("cutoff")
    ]
    w3, w6 = wape(short), wape(df.h > 0)
    return {
        "wape3": w3,
        "wape6": w6,
        "bias": float((df.yhat - df.actual).sum() / df.actual.sum()) if df.actual.sum() else 0.0,
        "score": (w3 + w6) / 2,
        "folds": folds,
    }


def as_date(x) -> date:
    return pd.Timestamp(x).date()
