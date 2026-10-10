"""
Дашборды «Продажи»: обзор, товарные группы, сервис, салоны, сезонность.

Каждый дашборд читает свою витрину (marts.models). Агрегации тут — только по маленьким
таблицам витрин (тысячи строк), поэтому страницы открываются быстро.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from django.contrib import admin
from django.db import DatabaseError
from django.db.models import Max, Min, Sum
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from catalog.models import DemandType, Item, ItemGroup
from core.models import Jobs
from marts.models import (
    MartGroupMonth,
    MartItemMonth,
    MartMeta,
    MartSalesMonth,
    MartSeason,
    MartServiceItems,
    MartServiceMonth,
)
from sales.models import Department, DocKind

from . import charts
from .period import PRESETS, SEASON_MONTHS, add_months, month_label, parse_filters

DASHBOARDS = [
    ("overview", "Обзор продаж", "monitoring"),
    ("groups", "Товарные группы", "category"),
    ("service", "Сервис (наряды)", "build"),
    ("departments", "Салоны", "storefront"),
    ("season", "Сезонность", "calendar_month"),
]

SALES_KINDS = [DocKind.SERVICE, DocKind.SALE, DocKind.RETAIL]

# В 1С цена продажи — с НДС, себестоимость — без НДС: маржа считается от выручки без НДС
# (ставка на дату документа: 20% до 2025 г., 22% с 2026 г. — см. sql/marts/_base.sql).
MARGIN_TIP = ("Выручка без НДС минус себестоимость. В 1С цены продажи — с НДС, а себестоимость — без НДС, "
              "поэтому НДС из выручки сначала убираем: 20% — по 2025 г., 22% — с 2026 г. "
              "Маржинальность = маржа ÷ выручка без НДС.")


def _margin(r):
    """Маржинальность строки витрины: (выручка без НДС − себестоимость) / выручка без НДС."""
    return _ratio((r["revenue_net"] or 0) - (r["cost"] or 0), r["revenue_net"])


# ---------------------------------------------------------------------------
# Общее
# ---------------------------------------------------------------------------

def _ratio(a, b):
    a, b = float(a or 0), float(b or 0)
    return a / b if b else None


def _yoy(cur, prev):
    cur, prev = float(cur or 0), float(prev or 0)
    return (cur - prev) / abs(prev) if prev else None


def _sum(qs, *fields):
    agg = qs.aggregate(**{f: Sum(f) for f in fields})
    return {f: float(agg[f] or 0) for f in fields}


def _meta():
    """Отметка пересчёта витрин + признак «устарели» (правили номенклатуру после пересчёта)."""
    try:
        meta = MartMeta.objects.first()
    except DatabaseError:
        return None
    if not meta:
        return None
    built = datetime.fromtimestamp(meta.built_at, tz=timezone.get_current_timezone())
    changed = Item.objects.filter(updated__gt=built).count()
    return {"built": built, "last_month": meta.last_month, "last_date": meta.last_date, "stale_items": changed}


def _rebuild_url(request):
    job = Jobs.objects.filter(command="build_marts").first()
    if not job:
        return None
    return reverse("admin:core_jobs_run_command", args=[job.pk]) + "?next=" + request.get_full_path()


def _bounds():
    agg = MartSalesMonth.objects.aggregate(first=Min("month"), last=Max("month"))
    first, last = agg["first"], agg["last"]
    if isinstance(first, str):
        first, last = date.fromisoformat(first[:10]), date.fromisoformat(last[:10])
    return first, last


def _render(request, template, slug, title, ctx):
    context = {
        **admin.site.each_context(request),
        "title": title,
        "dashboards": [(s, t, i, reverse(f"sales_dashboard_{s}")) for s, t, i in DASHBOARDS],
        "current": slug,
        **ctx,
    }
    return TemplateResponse(request, template, context)


def dashboard(slug, title, use_kind=True):
    """Декоратор: общие фильтры, мета пересчёта, «витрины не построены»."""

    def wrap(fn):
        def view(request):
            meta = _meta()
            base = {"meta": meta, "rebuild_url": _rebuild_url(request)}
            if not meta:
                return _render(request, "sales/dashboards/empty.html", slug, title, base)
            first, last = _bounds()
            if not first:
                return _render(request, "sales/dashboards/empty.html", slug, title, base)
            f = parse_filters(request, first, last, use_kind=use_kind)
            ctx = {
                **base,
                "f": f,
                "presets": PRESETS,
                "departments": Department.objects.all(),
                "kinds": [(k.value, k.label) for k in SALES_KINDS + [DocKind.RETURN]],
                "use_kind": use_kind,
                "first_month": first.strftime("%Y-%m"),
                "last_month": last.strftime("%Y-%m"),
                **fn(request, f),
            }
            return _render(request, f"sales/dashboards/{slug}.html", slug, title, ctx)

        view.__name__ = f"dashboard_{slug}"
        return admin.site.admin_view(view)

    return wrap


# ---------------------------------------------------------------------------
# 1. Обзор продаж
# ---------------------------------------------------------------------------

@dashboard("overview", "Обзор продаж")
def overview(request, f):
    cur_qs = f.qs(MartSalesMonth.objects)
    prev_qs = f.qs(MartSalesMonth.objects, prev=True)
    fields = ("revenue", "revenue_net", "cost", "qty", "docs", "lines", "lines_no_revenue")
    cur, prev = _sum(cur_qs, *fields), _sum(prev_qs, *fields)
    has_prev = f.period.has_prev

    kpis = [
        {"title": "Выручка с НДС", "value": cur["revenue"], "fmt": "mln", "yoy": _yoy(cur["revenue"], prev["revenue"]) if has_prev else None},
        {"title": "Валовая маржа", "value": cur["revenue_net"] - cur["cost"], "fmt": "mln",
         "tip": MARGIN_TIP,
         "sub": _ratio(cur["revenue_net"] - cur["cost"], cur["revenue_net"]), "sub_label": "маржинальность (от выручки без НДС)",
         "yoy": _yoy(cur["revenue_net"] - cur["cost"], prev["revenue_net"] - prev["cost"]) if has_prev else None},
        {"title": "Продано, шт.", "value": cur["qty"], "fmt": "num", "yoy": _yoy(cur["qty"], prev["qty"]) if has_prev else None},
        {"title": "Документов", "value": cur["docs"], "fmt": "num", "yoy": _yoy(cur["docs"], prev["docs"]) if has_prev else None,
         "sub": _ratio(cur["revenue"], cur["docs"]), "sub_label": "₽ на документ", "sub_fmt": "rub"},
    ]

    # --- динамика по месяцам: выручка текущего периода и год назад
    months = f.period.months
    by_month = {r["month"]: r for r in cur_qs.values("month").annotate(revenue=Sum("revenue"), cost=Sum("cost"))}
    by_month_prev = {r["month"]: r["revenue"] for r in prev_qs.values("month").annotate(revenue=Sum("revenue"))}
    labels = [month_label(m) for m in months]
    series = [{"label": "Выручка", "data": [round(by_month.get(m, {}).get("revenue") or 0) for m in months],
               "color": charts.PALETTE[0], "fill": True}]
    if has_prev:
        series.append({"label": "Год назад", "data": [round(by_month_prev.get(add_months(m, -12)) or 0) for m in months],
                       "color": charts.MUTED, "dashed": True})
    chart_trend = charts.line(labels, series)

    # --- каналы по месяцам
    kind_month = defaultdict(float)
    for r in cur_qs.values("month", "kind").annotate(revenue=Sum("revenue")):
        kind_month[(r["month"], r["kind"])] = r["revenue"] or 0
    chart_kinds = charts.bar(labels, [
        {"label": DocKind(k).label, "data": [round(kind_month[(m, k)]) for m in months], "color": charts.KIND_COLORS[k]}
        for k in SALES_KINDS
    ], stacked=True)

    # --- таблица каналов
    prev_kind = {r["kind"]: r for r in prev_qs.values("kind").annotate(revenue=Sum("revenue"))}
    kinds = []
    for r in cur_qs.values("kind").annotate(revenue=Sum("revenue"), revenue_net=Sum("revenue_net"), cost=Sum("cost"),
                                            docs=Sum("docs"), qty=Sum("qty")).order_by("-revenue"):
        kinds.append({
            "kind": r["kind"], "label": DocKind(r["kind"]).label, "color": charts.KIND_COLORS.get(r["kind"]),
            "revenue": r["revenue"], "share": _ratio(r["revenue"], cur["revenue"]),
            "margin": _margin(r),
            "docs": r["docs"], "qty": r["qty"],
            "yoy": _yoy(r["revenue"], prev_kind.get(r["kind"], {}).get("revenue")) if has_prev else None,
        })

    # --- топ групп (из витрины групп)
    g_qs = f.qs(MartGroupMonth.objects)
    names = dict(ItemGroup.objects.values_list("id", "name"))
    top_groups = [
        {"id": r["group_id"], "name": names.get(r["group_id"], "— без группы"), "revenue": r["revenue"],
         "share": _ratio(r["revenue"], cur["revenue"])}
        for r in g_qs.values("group_id").annotate(revenue=Sum("revenue")).order_by("-revenue")[:8]
    ]

    return {
        "kpis": kpis, "chart_trend": chart_trend, "chart_kinds": chart_kinds, "kinds_table": kinds,
        "top_groups": top_groups, "no_revenue_share": _ratio(cur["lines_no_revenue"], cur["lines"]),
    }


# ---------------------------------------------------------------------------
# 2. Товарные группы
# ---------------------------------------------------------------------------

@dashboard("groups", "Товарные группы")
def groups(request, f):
    demand = request.GET.get("demand") or ""
    group_id = request.GET.get("group")
    groups_by_id = {g.id: g for g in ItemGroup.objects.all()}

    def base(prev=False):
        qs = f.qs(MartGroupMonth.objects, prev=prev)
        if demand:
            qs = qs.filter(group__demand_type=demand)
        return qs

    cur_qs, prev_qs = base(), base(prev=True)
    total = _sum(cur_qs, "revenue", "revenue_net", "cost", "qty")
    prev_by = {r["group_id"]: r["revenue"] for r in prev_qs.values("group_id").annotate(revenue=Sum("revenue"))}

    rows = []
    for r in cur_qs.values("group_id").annotate(revenue=Sum("revenue"), revenue_net=Sum("revenue_net"), cost=Sum("cost"),
                                                qty=Sum("qty"), lines=Sum("lines")).order_by("-revenue"):
        g = groups_by_id.get(r["group_id"])
        rows.append({
            "id": r["group_id"], "name": g.name if g else "— без группы",
            "demand": g.get_demand_type_display() if g else "", "demand_code": g.demand_type if g else "",
            "revenue": r["revenue"], "share": _ratio(r["revenue"], total["revenue"]),
            "margin": _margin(r),
            "qty": r["qty"], "lines": r["lines"],
            "yoy": _yoy(r["revenue"], prev_by.get(r["group_id"])) if f.period.has_prev else None,
        })

    top = rows[:12]
    chart_top = charts.bar([r["name"] for r in top], [
        {"label": "Выручка", "data": [round(r["revenue"] or 0) for r in top], "color": charts.PALETTE[0]},
    ], horizontal=True, legend=False)

    # типы спроса
    by_demand = defaultdict(float)
    for r in rows:
        by_demand[r["demand_code"] or "other"] += r["revenue"] or 0
    d_items = sorted(by_demand.items(), key=lambda x: -x[1])
    chart_demand = charts.doughnut(
        [DemandType(k).label for k, _ in d_items], [round(v) for _, v in d_items],
        [charts.PALETTE[i % len(charts.PALETTE)] for i in range(len(d_items))],
    )

    # детализация выбранной группы
    detail = None
    if group_id and group_id.isdigit() and int(group_id) in groups_by_id:
        gid = int(group_id)
        g = groups_by_id[gid]
        months = f.period.months
        cur_m = {r["month"]: r["revenue"] for r in f.qs(MartGroupMonth.objects).filter(group_id=gid).values("month").annotate(revenue=Sum("revenue"))}
        prev_m = {r["month"]: r["revenue"] for r in f.qs(MartGroupMonth.objects, prev=True).filter(group_id=gid).values("month").annotate(revenue=Sum("revenue"))}
        series = [{"label": g.name, "data": [round(cur_m.get(m) or 0) for m in months], "color": charts.PALETTE[0], "fill": True}]
        if f.period.has_prev:
            series.append({"label": "Год назад", "data": [round(prev_m.get(add_months(m, -12)) or 0) for m in months],
                           "color": charts.MUTED, "dashed": True})
        items_qs = f.qs(MartItemMonth.objects).filter(item__group_id=gid)
        items = list(
            items_qs.values("item_id", "item__article", "item__name")
            .annotate(revenue=Sum("revenue"), qty=Sum("qty"), docs=Sum("docs"))
            .order_by("-revenue")[:25]
        )
        detail = {
            "group": g, "chart": charts.line([month_label(m) for m in months], series), "items": items,
            "items_url": reverse("admin:catalog_item_changelist") + f"?group__id__exact={gid}",
        }

    return {
        "rows": rows, "total": total, "chart_top": chart_top, "chart_demand": chart_demand,
        "demand": demand, "demand_choices": DemandType.choices, "detail": detail,
    }


# ---------------------------------------------------------------------------
# 3. Сервис (наряды)
# ---------------------------------------------------------------------------

@dashboard("service", "Сервис (наряды)", use_kind=False)
def service(request, f):
    fields = ("orders", "orders_consumable", "orders_no_revenue", "lines", "qty", "qty_consumable", "revenue", "cost")
    cur_qs, prev_qs = f.qs(MartServiceMonth.objects), f.qs(MartServiceMonth.objects, prev=True)
    cur, prev = _sum(cur_qs, *fields), _sum(prev_qs, *fields)
    has_prev = f.period.has_prev

    kpis = [
        {"title": "Нарядов", "value": cur["orders"], "fmt": "num", "yoy": _yoy(cur["orders"], prev["orders"]) if has_prev else None},
        {"title": "Позиций на наряд", "value": _ratio(cur["lines"], cur["orders"]), "fmt": "dec",
         "yoy": _yoy(_ratio(cur["lines"], cur["orders"]), _ratio(prev["lines"], prev["orders"])) if has_prev else None},
        {"title": "Расходников на наряд, шт.", "value": _ratio(cur["qty_consumable"], cur["orders"]), "fmt": "dec",
         "sub": _ratio(cur["orders_consumable"], cur["orders"]), "sub_label": "нарядов с расходниками",
         "yoy": _yoy(_ratio(cur["qty_consumable"], cur["orders"]), _ratio(prev["qty_consumable"], prev["orders"])) if has_prev else None},
        {"title": "Выручка запчастей в нарядах", "value": cur["revenue"], "fmt": "mln",
         "sub": _ratio(cur["orders_no_revenue"], cur["orders"]), "sub_label": "нарядов без выручки (гарантия?)",
         "yoy": _yoy(cur["revenue"], prev["revenue"]) if has_prev else None},
    ]

    months = f.period.months
    labels = [month_label(m) for m in months]
    cur_m = {r["month"]: r for r in cur_qs.values("month").annotate(orders=Sum("orders"), qty_consumable=Sum("qty_consumable"))}
    prev_m = {r["month"]: r["orders"] for r in prev_qs.values("month").annotate(orders=Sum("orders"))}
    series = [{"label": "Нарядов", "data": [int(cur_m.get(m, {}).get("orders") or 0) for m in months], "color": charts.KIND_COLORS["service"]}]
    if has_prev:
        series.append({"label": "Год назад", "data": [int(prev_m.get(add_months(m, -12)) or 0) for m in months], "color": "#cbd5e1"})
    chart_orders = charts.bar(labels, series)
    chart_norm = charts.line(labels, [{
        "label": "Расходников на наряд",
        "data": [round(_ratio(cur_m.get(m, {}).get("qty_consumable"), cur_m.get(m, {}).get("orders")) or 0, 2) for m in months],
        "color": charts.PALETTE[1],
    }], legend=False)

    # по салонам
    depts = dict((d.id, d) for d in Department.objects.all())
    prev_d = {r["department_id"]: r["orders"] for r in prev_qs.values("department_id").annotate(orders=Sum("orders"))}
    by_dept = []
    for r in cur_qs.values("department_id").annotate(orders=Sum("orders"), lines=Sum("lines"), qty_consumable=Sum("qty_consumable"),
                                                       revenue=Sum("revenue"), orders_no_revenue=Sum("orders_no_revenue")).order_by("-orders"):
        d = depts.get(r["department_id"])
        by_dept.append({
            "name": str(d) if d else "—", "orders": r["orders"], "share": _ratio(r["orders"], cur["orders"]),
            "lines_per": _ratio(r["lines"], r["orders"]), "cons_per": _ratio(r["qty_consumable"], r["orders"]),
            "revenue": r["revenue"], "no_rev": _ratio(r["orders_no_revenue"], r["orders"]),
            "yoy": _yoy(r["orders"], prev_d.get(r["department_id"])) if has_prev else None,
        })

    # что уходит в наряды: норма на наряд
    items_qs = MartServiceItems.objects.filter(month__gte=f.period.start, month__lte=f.period.end)
    if f.dept:
        items_qs = items_qs.filter(department_id=f.dept)
    total_orders = cur["orders"] or 1
    items = []
    for r in (items_qs.values("item_id", "item__article", "item__name", "item__group__name", "item__group__demand_type")
              .annotate(orders=Sum("orders"), qty=Sum("qty"), revenue=Sum("revenue")).order_by("-orders")[:30]):
        items.append({**r, "share": r["orders"] / total_orders, "norm": r["qty"] / total_orders,
                      "per_order": _ratio(r["qty"], r["orders"])})

    return {"kpis": kpis, "chart_orders": chart_orders, "chart_norm": chart_norm, "by_dept": by_dept, "items": items}


# ---------------------------------------------------------------------------
# 4. Салоны
# ---------------------------------------------------------------------------

@dashboard("departments", "Салоны")
def departments(request, f):
    depts = {d.id: d for d in Department.objects.all()}
    cur_qs, prev_qs = f.qs(MartSalesMonth.objects), f.qs(MartSalesMonth.objects, prev=True)
    total = _sum(cur_qs, "revenue")["revenue"]
    prev_by = {r["department_id"]: r["revenue"] for r in prev_qs.values("department_id").annotate(revenue=Sum("revenue"))}

    kind_by = defaultdict(dict)
    for r in cur_qs.values("department_id", "kind").annotate(revenue=Sum("revenue"), docs=Sum("docs")):
        kind_by[r["department_id"]][r["kind"]] = r

    rows = []
    for r in cur_qs.values("department_id").annotate(revenue=Sum("revenue"), revenue_net=Sum("revenue_net"), cost=Sum("cost"),
                                                     docs=Sum("docs"), qty=Sum("qty")).order_by("-revenue"):
        did = r["department_id"]
        d = depts.get(did)
        k = kind_by[did]
        rows.append({
            "id": did, "name": d.name if d and d.name else "— название не задано", "prefix": d.prefix if d else "—",
            "revenue": r["revenue"], "share": _ratio(r["revenue"], total),
            "margin": _margin(r),
            "docs": r["docs"], "orders": (k.get("service") or {}).get("docs") or 0,
            "service_share": _ratio((k.get("service") or {}).get("revenue"), r["revenue"]),
            "yoy": _yoy(r["revenue"], prev_by.get(did)) if f.period.has_prev else None,
        })

    labels = [r["prefix"] for r in rows]
    chart_mix = charts.bar(labels, [
        {"label": DocKind(k).label, "data": [round((kind_by[r["id"]].get(k) or {}).get("revenue") or 0) for r in rows],
         "color": charts.KIND_COLORS[k]}
        for k in SALES_KINDS
    ], stacked=True)

    months = f.period.months
    by_dm = defaultdict(float)
    for r in cur_qs.values("department_id", "month").annotate(revenue=Sum("revenue")):
        by_dm[(r["department_id"], r["month"])] = r["revenue"] or 0
    chart_trend = charts.line([month_label(m) for m in months], [
        {"label": r["prefix"], "data": [round(by_dm[(r["id"], m)]) for m in months], "color": charts.PALETTE[i % len(charts.PALETTE)]}
        for i, r in enumerate(rows[:6])
    ])
    return {"rows": rows, "total": total, "chart_mix": chart_mix, "chart_trend": chart_trend}


# ---------------------------------------------------------------------------
# 5. Сезонность
# ---------------------------------------------------------------------------

def season_profile(qs, metric: str, first: date, last: date) -> dict:
    """Профиль сезона (окт–сен): доля каждого месяца в сезоне, %, по полным сезонам.
    Общая функция для дашборда «Сезонность» и главной — цифры обязаны совпадать."""
    seasons = sorted({r for r in qs.values_list("season", flat=True).distinct()})
    full = [s for s in seasons if date(s, 10, 1) >= first and add_months(date(s, 10, 1), 11) <= last]
    current = [s for s in seasons if s not in full]

    by_sm = defaultdict(float)
    for r in qs.values("season", "season_month").annotate(v=Sum(metric)):
        by_sm[(r["season"], r["season_month"])] = r["v"] or 0

    def profile(s):
        tot = sum(by_sm[(s, m)] for m in range(1, 13))
        return [round(100 * by_sm[(s, m)] / tot, 1) if tot else 0 for m in range(1, 13)]

    avg = [round(sum(profile(s)[m] for s in full) / len(full), 1) for m in range(12)] if full else None
    return {"full": full, "current": current, "profile": profile, "avg": avg}


def home_figures() -> dict | None:
    """Цифры для плиток главной — тем же кодом и с теми же фильтрами по умолчанию, что и дашборды
    («Последние 12 мес.», все салоны, все каналы). Так плитка и дашборд совпадают до рубля."""
    from types import SimpleNamespace

    from django.http import QueryDict

    first, last = _bounds()
    if not first:
        return None
    f = parse_filters(SimpleNamespace(GET=QueryDict("")), first, last)
    cur, prev = _sum(f.qs(MartSalesMonth.objects), "revenue"), _sum(f.qs(MartSalesMonth.objects, prev=True), "revenue")
    o_cur, o_prev = _sum(f.qs(MartServiceMonth.objects), "orders"), _sum(f.qs(MartServiceMonth.objects, prev=True), "orders")
    has_prev = f.period.has_prev

    seasons = []
    for label, kind, url_q in (("Сервис", DocKind.SERVICE, "&kind=service"), ("Все каналы", None, "")):
        qs = MartSeason.objects.filter(kind=kind) if kind else MartSeason.objects.all()
        sp = season_profile(qs, "revenue", f.period.first, f.period.last)
        if sp["avg"]:
            seasons.append({"label": label, "avg": sp["avg"], "n": len(sp["full"]),
                            "url": reverse("sales_dashboard_season") + "?metric=revenue" + url_q})
    return {
        "period": f.period.label, "prev_period": f.period.prev_label if has_prev else None,
        "last": last, "revenue": cur["revenue"], "revenue_yoy": _yoy(cur["revenue"], prev["revenue"]) if has_prev else None,
        "orders": o_cur["orders"], "orders_yoy": _yoy(o_cur["orders"], o_prev["orders"]) if has_prev else None,
        "seasons": seasons,
    }


@dashboard("season", "Сезонность")
def season(request, f):
    """Сезонность считается по всей истории (полные сезоны), фильтры — салон, канал, группа."""
    metric = request.GET.get("metric") or "qty"
    if metric not in ("qty", "revenue"):
        metric = "qty"
    group_id = request.GET.get("group")

    qs = MartSeason.objects.all()
    if f.dept:
        qs = qs.filter(department_id=f.dept)
    if f.kind:
        qs = qs.filter(kind=f.kind)
    if group_id and group_id.isdigit():
        qs = qs.filter(group_id=int(group_id))

    sp = season_profile(qs, metric, f.period.first, f.period.last)
    full, current, profile, avg = sp["full"], sp["current"], sp["profile"], sp["avg"]

    series = [{"label": f"{s}/{str(s + 1)[2:]}", "data": profile(s), "color": charts.PALETTE[(i + 1) % len(charts.PALETTE)]}
              for i, s in enumerate(full[-4:])]
    if avg:
        series.insert(0, {"label": "Среднее", "data": avg, "color": charts.PALETTE[0], "fill": True})
    chart_profile = charts.line(SEASON_MONTHS, series, y_suffix="% сезона")

    # тепловая карта: группа × месяц сезона (доля месяца в году группы, по полным сезонам)
    heat_qs = qs.filter(season__in=full) if full else qs.none()
    gm = defaultdict(lambda: [0.0] * 12)
    for r in heat_qs.values("group_id", "season_month").annotate(v=Sum(metric)):
        gm[r["group_id"]][int(r["season_month"]) - 1] += r["v"] or 0
    names = dict(ItemGroup.objects.values_list("id", "name"))
    heat = []
    for gid, vals in sorted(gm.items(), key=lambda x: -sum(x[1])):
        tot = sum(vals)
        if tot <= 0:
            continue
        shares = [v / tot for v in vals]
        mx = max(shares) or 1
        peak = SEASON_MONTHS[shares.index(max(shares))]
        heat.append({"id": gid, "name": names.get(gid, "— без группы"), "total": tot,
                     "cells": [{"share": s, "rel": s / mx} for s in shares], "peak": peak})

    return {
        "chart_profile": chart_profile, "heat": heat[:40], "metric": metric, "season_months": SEASON_MONTHS,
        "full_seasons": [f"{s}/{str(s + 1)[2:]}" for s in full],
        "current_seasons": [f"{s}/{str(s + 1)[2:]}" for s in current],
        "groups_list": ItemGroup.objects.all(), "group_id": int(group_id) if group_id and group_id.isdigit() else None,
    }
