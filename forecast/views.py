"""
Дашборды «Прогноз»:
    • Прогноз — факт за 2 года + прогноз с коридором; для старого прогноза сразу виден и факт;
    • Проверка на прошлом — как лучшая модель прогнозировала с прошлых дат (бэктест)
      и как сохранённые прогнозы совпали с пришедшим фактом.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from django.contrib import admin
from django.db import DatabaseError
from django.db.models import Sum
from django.template.response import TemplateResponse
from django.urls import reverse

from core.models import Jobs
from catalog.models import Item, ItemGroup
from forecast.models import (
    SERIES_KINDS,
    BacktestPoint,
    ForecastGroup,
    ForecastItem,
    ForecastPoint,
    ForecastRun,
    PriceSource,
    Series,
    TuneRun,
)
from forecast.services.engine import params_label
from marts.models import MartItemMonth, MartMeta, MartSalesMonth
from sales.dashboards import charts
from sales.dashboards.period import add_months, month_label

TABS = [
    ("overview", "Прогноз", "trending_up"),
    ("qty", "Штуки", "inventory_2"),
    ("backtest", "Проверка на прошлом", "fact_check"),
]
SERIES_COLORS = {Series.SERVICE: "#D3141C", Series.SHOP: "#2a78d6", Series.TOTAL: "#D3141C"}
HISTORY_MONTHS = 24


# ---------------------------------------------------------------------------
# Общее
# ---------------------------------------------------------------------------

def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _ms(d: date) -> date:
    return date(d.year, d.month, 1)


def _actual(series: str) -> tuple[dict[date, float], date | None, date | None]:
    """Факт выручки по месяцам из витрины + последний полный месяц и последняя дата."""
    try:
        rows = (MartSalesMonth.objects.filter(kind__in=SERIES_KINDS[series])
                .values("month").annotate(rev=Sum("revenue")))
        actual = {_d(r["month"]): float(r["rev"] or 0) for r in rows}
        meta = MartMeta.objects.first()
    except DatabaseError:
        return {}, None, None
    if not meta or not actual:
        return actual, None, None
    last_date = _d(meta.last_date)
    nxt = date.fromordinal(last_date.toordinal() + 1)
    last_full = _ms(last_date) if nxt.day == 1 else add_months(_ms(last_date), -1)
    return actual, last_full, last_date


def _job_url(request, command):
    job = Jobs.objects.filter(command=command).first()
    if not job:
        return None
    return reverse("admin:core_jobs_run_command", args=[job.pk]) + "?next=" + request.get_full_path()


def _series(request) -> str:
    s = request.GET.get("series") or Series.TOTAL
    return s if s in Series.values else Series.TOTAL


def _ratio(a, b):
    return (a - b) / abs(b) if b else None


def _band_chart(labels, fact, forecast, lower, upper, last_year=None, color="#D3141C"):
    """Линии: факт, прогноз (пунктир), коридор (заливка между upper и lower), год назад."""
    datasets = [
        {"label": "Факт", "data": fact, "borderColor": "#111827", "backgroundColor": "#111827",
         "borderWidth": 2, "pointRadius": 2},
        {"label": "Прогноз", "data": forecast, "borderColor": color, "backgroundColor": color,
         "borderDash": [6, 4], "borderWidth": 2, "pointRadius": 2},
        {"label": "Коридор 80%: верх", "data": upper, "borderColor": "transparent", "backgroundColor": color + "22",
         "fill": "+1", "pointRadius": 0},
        {"label": "Коридор 80%: низ", "data": lower, "borderColor": "transparent", "backgroundColor": "transparent",
         "fill": False, "pointRadius": 0},
    ]
    if last_year:
        datasets.append({"label": "Год назад", "data": last_year, "borderColor": charts.MUTED,
                         "backgroundColor": charts.MUTED, "borderDash": [2, 3], "borderWidth": 1.5,
                         "pointRadius": 0})
    opts = charts._options(y_suffix="млн ₽")
    return json.dumps({"labels": labels, "datasets": datasets}, ensure_ascii=False), json.dumps(opts, ensure_ascii=False)


def _mln(v):
    return None if v is None else round(v / 1e6, 2)


def _render(request, slug, title, ctx):
    context = {
        **admin.site.each_context(request),
        "title": title,
        "dashboards": [(s, t, i, reverse(f"forecast_dashboard_{s}")) for s, t, i in TABS]
        + [("tune", "Подбор параметров", "tune", reverse("admin:forecast_tunerun_changelist"))],
        "current": slug,
        "series_list": Series.choices,
        "build_url": _job_url(request, "forecast_build"),
        "tune_url": _job_url(request, "forecast_tune"),
        **ctx,
    }
    return TemplateResponse(request, f"forecast/{slug}.html", context)


# ---------------------------------------------------------------------------
# 1. Прогноз
# ---------------------------------------------------------------------------

def overview(request):
    series = _series(request)
    runs = list(ForecastRun.objects.all()[:30])
    run = None
    if request.GET.get("run", "").isdigit():
        run = ForecastRun.objects.filter(pk=request.GET["run"]).first()
    run = run or (runs[0] if runs else None)
    if not run:
        return _render(request, "overview", "Прогноз", {"run": None, "series": series})

    actual, last_full, last_date = _actual(series)
    points = list(run.points.filter(series=series).order_by("month"))
    first = points[0].month if points else _ms(run.data_end)
    start = add_months(first, -HISTORY_MONTHS)
    months = [add_months(start, i) for i in range(HISTORY_MONTHS + len(points))]
    pmap = {p.month: p for p in points}

    def known(m):  # месяц уже закрыт фактом (в т.ч. после даты прогноза)
        return last_full is not None and m <= last_full

    fact = [_mln(actual.get(m)) if known(m) else None for m in months]
    fc, lo, hi, ly = [], [], [], []
    for i, m in enumerate(months):
        p = pmap.get(m)
        if p:
            fc.append(_mln(p.expected))
            lo.append(_mln(p.actual_before + p.lower))
            hi.append(_mln(p.actual_before + p.upper))
            ly.append(_mln(actual.get(add_months(m, -12))))
        elif i + 1 < len(months) and months[i + 1] == first and known(m):
            v = _mln(actual.get(m))  # стыкуем прогноз с последним фактом
            fc.append(v), lo.append(v), hi.append(v), ly.append(None)
        else:
            fc.append(None), lo.append(None), hi.append(None), ly.append(None)
    chart = _band_chart([month_label(m) for m in months], fact, fc, lo, hi, ly, SERIES_COLORS[series])

    rows = []
    for p in points:
        prev = actual.get(add_months(p.month, -12))
        fact_m = actual.get(p.month) if known(p.month) else None
        rows.append({
            "month": p.month, "label": month_label(p.month), "expected": p.expected,
            "lower": p.actual_before + p.lower, "upper": p.actual_before + p.upper,
            "actual_before": p.actual_before, "prev": prev, "yoy": _ratio(p.expected, prev),
            "fact": fact_m, "err": _ratio(p.expected, fact_m) if fact_m else None,
        })

    def window(a, b):
        sel = rows[a:b]
        exp = sum(r["expected"] for r in sel)
        prev = sum(r["prev"] or 0 for r in sel)
        return exp, _ratio(exp, prev) if all(r["prev"] for r in sel) else None, sel

    first_partial = bool(points and points[0].actual_before)
    off = 1 if first_partial else 0
    n3, y3, s3 = window(off, off + 3)
    n6, y6, s6 = window(off, off + 6)
    acc = _accuracy(series)
    kpis = []
    if first_partial:
        r0 = rows[0]
        kpis.append({"title": f"{r0['label']}: ожидание", "value": r0["expected"], "fmt": "mln", "yoy": r0["yoy"],
                     "sub": r0["actual_before"], "sub_fmt": "rub", "sub_label": "₽ факт на дату"})
    if s3:
        kpis.append({"title": f"{s3[0]['label']} – {s3[-1]['label']}", "value": n3, "fmt": "mln", "yoy": y3})
    if len(s6) > 3:
        kpis.append({"title": f"{s6[0]['label']} – {s6[-1]['label']}", "value": n6, "fmt": "mln", "yoy": y6})

    stale = last_date and last_date > run.data_end
    return _render(request, "overview", "Прогноз", {
        "run": run, "runs": runs, "series": series, "series_label": Series(series).label,
        "chart": chart, "rows": rows, "kpis": kpis, "acc": acc, "stale": stale, "last_date": last_date,
        "params": [(Series(s).label, params_label(p)) for s, p in run.params.items()],
        "has_fact": any(r["fact"] for r in rows),
    })


# ---------------------------------------------------------------------------
# 2. Проверка на прошлом
# ---------------------------------------------------------------------------

def _tune_runs(series):
    names = [Series.SERVICE, Series.SHOP] if series == Series.TOTAL else [series]
    runs = [TuneRun.objects.filter(series=s).first() for s in names]
    return runs if all(runs) else []


def _backtest_points(series) -> list[dict]:
    """Точки бэктеста; для «Всего» — сумма двух рядов по общим (отсечка, месяц)."""
    runs = _tune_runs(series)
    if not runs:
        return []
    acc = defaultdict(lambda: {"actual": 0.0, "yhat": 0.0, "lower": 0.0, "upper": 0.0, "n": 0})
    for p in BacktestPoint.objects.filter(run__in=runs):
        a = acc[(p.cutoff, p.month, p.h)]
        a["actual"] += p.actual
        a["yhat"] += p.yhat
        a["lower"] += p.lower   # для «Всего» коридор — сумма границ (шире настоящего, с запасом)
        a["upper"] += p.upper
        a["n"] += 1
    return [{"cutoff": c, "month": m, "h": h, **v} for (c, m, h), v in sorted(acc.items()) if v["n"] == len(runs)]


def _sum_errors(points, max_h=None) -> list[float]:
    """Ошибка суммы за период по каждой дате проверки: (прогноз − факт) / факт."""
    by_cut = defaultdict(lambda: [0.0, 0.0])
    for p in points:
        if max_h is None or p["h"] <= max_h:
            by_cut[p["cutoff"]][0] += p["yhat"]
            by_cut[p["cutoff"]][1] += p["actual"]
    return [(f - a) / a for f, a in by_cut.values() if a]


def _accuracy(series):
    """Точность на понятном языке: на сколько в среднем ошиблись в сумме за 3 и за 6 месяцев.
    Помесячная ошибка (WAPE) — только для подбора параметров."""
    pts = _backtest_points(series)
    if not pts:
        return None
    runs = _tune_runs(series)
    horizon = runs[0].horizon
    e6, e3 = _sum_errors(pts), _sum_errors(pts, 3)
    a = sum(p["actual"] for p in pts)
    bias = sum(p["yhat"] - p["actual"] for p in pts) / a if a else 0.0
    mean = lambda xs: sum(abs(x) for x in xs) / len(xs) if xs else None  # noqa: E731
    return {
        "horizon": horizon, "short": min(3, horizon),
        "sum6": mean(e6), "sum6_min": min(e6), "sum6_max": max(e6),
        "sum6_within10": sum(abs(x) <= 0.10 for x in e6), "n": len(e6),
        "sum3": mean(e3), "sum3_min": min(e3), "sum3_max": max(e3),
        "bias": bias, "bias_word": "занижает" if bias < -0.02 else "завышает" if bias > 0.02 else None,
        "bias_abs": abs(bias),
        "cutoffs": len({p["cutoff"] for p in pts}), "created": max(r.created for r in runs),
    }


def backtest(request):
    series = _series(request)
    pts = _backtest_points(series)
    ctx = {"series": series, "series_label": Series(series).label}
    ctx["saved"] = _saved_vs_fact(series)
    if not pts:
        return _render(request, "backtest", "Проверка на прошлом", {**ctx, "acc": None})

    actual, last_full, _ = _actual(series)
    cutoffs = sorted({p["cutoff"] for p in pts})
    sel = request.GET.get("cutoff")
    cutoff = next((c for c in cutoffs if str(c) == sel), cutoffs[-1])

    # график выбранной отсечки: год факта до неё + прогноз с коридором и факт после
    cp = [p for p in pts if p["cutoff"] == cutoff]
    start = add_months(cutoff, -12)
    months = [add_months(start, i) for i in range(12 + len(cp))]
    cmap = {p["month"]: p for p in cp}
    fact, fc, lo, hi = [], [], [], []
    for m in months:
        p = cmap.get(m)
        fact.append(_mln(p["actual"] if p else actual.get(m)))
        if p:
            fc.append(_mln(p["yhat"])), lo.append(_mln(p["lower"])), hi.append(_mln(p["upper"]))
        elif m == add_months(cutoff, -1):
            v = _mln(actual.get(m))
            fc.append(v), lo.append(v), hi.append(v)
        else:
            fc.append(None), lo.append(None), hi.append(None)
    chart = _band_chart([month_label(m) for m in months], fact, fc, lo, hi, color=SERIES_COLORS[series])

    # по отсечкам: сумма прогноза и факта на горизонте
    by_cut = []
    for c in cutoffs:
        g = [p for p in pts if p["cutoff"] == c]
        a, f = sum(p["actual"] for p in g), sum(p["yhat"] for p in g)
        by_cut.append({"cutoff": c, "label": f"с {month_label(c)}", "actual": a, "yhat": f,
                       "err": _ratio(f, a),
                       "first": month_label(g[0]["month"]), "last": month_label(g[-1]["month"])})
    bars = charts.bar(
        [r["label"] for r in by_cut],
        [{"label": "Факт", "data": [_mln(r["actual"]) for r in by_cut], "color": "#111827"},
         {"label": "Прогноз", "data": [_mln(r["yhat"]) for r in by_cut], "color": SERIES_COLORS[series]}],
        y_suffix="млн ₽",
    )
    cut_rows = [{**p, "label": month_label(p["month"]), "err": _ratio(p["yhat"], p["actual"])} for p in cp]

    runs = _tune_runs(series)
    return _render(request, "backtest", "Проверка на прошлом", {
        **ctx, "acc": _accuracy(series), "chart": chart, "bars": bars, "by_cut": by_cut,
        "cutoffs": cutoffs, "cutoff": cutoff, "cut_rows": cut_rows,
        "params": [(Series(r.series).label, params_label(r.best)) for r in runs],
        "tune_links": [(Series(r.series).label, reverse("admin:forecast_tunerun_change", args=[r.pk])) for r in runs],
    })


def _saved_vs_fact(series):
    """Сохранённые прогнозы на месяцы, по которым уже есть полный факт."""
    actual, last_full, _ = _actual(series)
    if not last_full:
        return []
    out = []
    pts = (ForecastPoint.objects.filter(series=series, month__lte=last_full)
           .select_related("run").order_by("-run__created", "month"))
    for p in pts:
        if p.month <= p.run.data_end and not p.actual_before:
            continue
        fact = actual.get(p.month)
        if not fact:
            continue
        out.append({"run": p.run, "month": month_label(p.month), "expected": p.expected,
                    "lower": p.actual_before + p.lower, "upper": p.actual_before + p.upper, "fact": fact,
                    "err": _ratio(p.expected, fact),
                    "inside": p.actual_before + p.lower <= fact <= p.actual_before + p.upper,
                    "partial": bool(p.actual_before)})
    return out


# ---------------------------------------------------------------------------
# 3. Штуки: лестница по группам и артикулам
# ---------------------------------------------------------------------------

def _ly_qty(kinds, months, by):
    """Факт штук за те же месяцы год назад: {group_id | item_id: qty} (группа — текущая)."""
    if not months:
        return {}
    ly = [add_months(m, -12) for m in months]
    try:
        rows = (MartItemMonth.objects.filter(kind__in=kinds, month__gte=min(ly), month__lte=max(ly))
                .values(by).annotate(q=Sum("qty")))
        return {r[by]: float(r["q"] or 0) for r in rows}
    except DatabaseError:
        return {}


def _stock_params(request):
    """Срок поставки и уровень сервиса: из формы, иначе — последние выбранные (в сессии
    пользователя), иначе — по умолчанию. Так значения держатся при переходах, пересчёте и выгрузке."""
    from forecast.services import stock

    saved = request.session.get("f7_stock", {})
    try:
        lt = max(1, min(6, int(request.GET.get("lt") or saved.get("lt") or stock.LEAD_TIME)))
    except (TypeError, ValueError):
        lt = stock.LEAD_TIME
    try:
        sl = max(50.0, min(99.9, float(str(request.GET.get("sl") or saved.get("sl") or stock.SERVICE_LEVEL * 100)
                                       .replace(",", ".")))) / 100
    except (TypeError, ValueError):
        sl = stock.SERVICE_LEVEL
    request.session["f7_stock"] = {"lt": lt, "sl": round(sl * 100, 1)}
    return lt, sl


def _qty_context(request):
    series = request.GET.get("series") or Series.TOTAL
    series = series if series in Series.values else Series.TOTAL
    runs = list(ForecastRun.objects.all()[:30])
    run = None
    if request.GET.get("run", "").isdigit():
        run = ForecastRun.objects.filter(pk=request.GET["run"]).first()
    run = run or (runs[0] if runs else None)
    group_id = request.GET.get("group")
    group_id = int(group_id) if group_id and group_id.isdigit() else None
    lt, sl = _stock_params(request)
    return run, runs, series, group_id, lt, sl


def qty(request):
    from forecast.services import stock

    run, runs, series, group_id, lt, sl = _qty_context(request)
    procurement = series == Series.TOTAL
    ctx = {"run": run, "runs": runs, "series": series, "series_label": Series(series).label,
           "groups_list": ItemGroup.objects.order_by("sort", "name"), "group_id": group_id,
           "lt": lt, "sl": round(sl * 100, 1), "z": stock.z_value(sl), "rare": stock.RARE_MONTHS,
           "procurement": procurement, "ladder_url": _job_url(request, "forecast_ladder")}
    if not run or not run.items.exists():
        return _render(request, "qty", "Прогноз в штуках", {**ctx, "empty": True})

    rows, hz = stock.item_rows(run, stock.series_names(series), lt, sl, group_id=group_id, procurement=procurement)
    full = hz.full
    m3, m6, mlt = full[:3], full[:6], full[:lt]
    span = lambda ms: f"{month_label(ms[0])} – {month_label(ms[-1])}" if ms else ""  # noqa: E731
    ctx["cols"] = {"rest": month_label(hz.partial) if hz.partial else None, "m3": span(m3), "m6": span(m6),
                   "lt": span(mlt)}
    ctx["horizon6"] = len(m6)
    if len(full) < lt:
        ctx["lt_warn"] = f"прогноз есть только на {len(full)} мес. — срок поставки урезан"
    kinds = SERIES_KINDS[series]

    keys = ("rest", "q3", "q6", "q_lt", "safety", "revenue6")
    if group_id is None:
        acc = defaultdict(lambda: {**{k: 0.0 for k in keys}, "rop": 0, "rop_cost": 0.0, "n": 0, "regular": 0})
        for r in rows:
            a = acc[r["group_id"]]
            for k in keys:
                a[k] += r[k]
            a["n"] += 1
            if procurement:
                a["rop"] += r["rop"]
                a["rop_cost"] += r["rop_cost"] or 0
            if r["demand"] not in ("редкий", "нет продаж"):
                a["regular"] += 1
        ly = _ly_qty(kinds, m6, "item__group")
        gnames = {g.pk: g.name for g in ItemGroup.objects.all()}
        total_r6 = sum(a["revenue6"] for a in acc.values()) or 1
        group_rows = sorted((
            {"id": gid, "name": gnames.get(gid, "Без группы"), **a, "share": a["revenue6"] / total_r6,
             "ly": ly.get(gid), "yoy": _ratio(a["q6"], ly.get(gid) or 0)}
            for gid, a in acc.items()), key=lambda r: -r["revenue6"])
        tot = {k: sum(r[k] for r in group_rows) for k in (*keys, "rop", "rop_cost", "n", "regular")}
        tot["ly"] = sum(r["ly"] or 0 for r in group_rows)
        tot["yoy"] = _ratio(tot["q6"], tot["ly"])
        ctx.update({"group_rows": group_rows, "tot": tot})
    else:
        ly = _ly_qty(kinds, m6, "item")
        for r in rows:
            r["ly"] = ly.get(r["item_id"])
        ctx.update({"item_rows": rows, "group": ItemGroup.objects.filter(pk=group_id).first(),
                    "tot": {k: sum((r[k] or 0) for r in rows) for k in (*keys, "rop", "rop_cost")}})

    ctx["export_url"] = reverse("forecast_qty_export") + "?" + request.GET.urlencode()
    return _render(request, "qty", "Прогноз в штуках", ctx)


def qty_export(request):
    from django.http import HttpResponse

    from forecast.services.export import build_workbook

    run, _, series, _, lt, sl = _qty_context(request)
    if not run:
        return HttpResponse("Прогноза ещё нет", status=404)
    wb, filename = build_workbook(run, lt=lt, service_level=sl)
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f"attachment; filename=\"{filename}\""
    wb.save(response)
    return response


overview = admin.site.admin_view(overview)
qty = admin.site.admin_view(qty)
qty_export = admin.site.admin_view(qty_export)
backtest = admin.site.admin_view(backtest)
