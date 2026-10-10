"""
Страховой запас и точка заказа по прогнозу в штуках (лестница) и статистике спроса.

    прогноз на срок поставки = прогноз продаж на первые LT полных месяцев
    страховой запас          = z × CV × средний прогноз в месяц × √LT
    точка заказа             = прогноз на срок поставки + страховой запас (вверх до целого);
                               у редкого спроса — без запаса и с обычным округлением

Когда остаток (склад + в пути) опускается до точки заказа — пора заказывать.
CV — по 12 полным месяцам факта, нулевые месяцы входят. Редкий спрос (продажи меньше чем
в RARE_MONTHS месяцах из 12) — формула для него не годится: страховой запас 0, кандидат «под заказ».
z — из уровня сервиса: 95% → 1,64 (в 95% случаев запаса хватит до прихода поставки).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist

from catalog.models import Item
from forecast.models import ForecastItem, ForecastRun, ItemDemandStats, PriceSource, Series

LEAD_TIME = 4          # средний срок поставки, мес.
SERVICE_LEVEL = 0.95   # уровень сервиса
RARE_MONTHS = 4        # меньше стольких месяцев с продажами из 12 — редкий спрос

DEMAND_CLASSES = [  # (верхняя граница CV, название)
    (0.5, "стабильный"),
    (1.0, "колеблется"),
    (math.inf, "нерегулярный"),
]


def z_value(service_level: float) -> float:
    return NormalDist().inv_cdf(min(max(service_level, 0.5), 0.999))


def demand_class(months12: int | None, cv: float | None) -> str:
    if not months12:
        return "нет продаж"
    if months12 < RARE_MONTHS or cv is None:
        return "редкий"
    return next(name for limit, name in DEMAND_CLASSES if cv <= limit)


@dataclass
class Horizon:
    months: list[date]        # все месяцы прогноза
    partial: date | None      # месяц, в котором кончается факт (в прогнозе — только остаток)
    full: list[date]          # полные месяцы после него


def horizon(run: ForecastRun) -> Horizon:
    months = sorted(set(run.items.values_list("month", flat=True)))
    if not months:
        return Horizon([], None, [])
    nxt = date.fromordinal(run.data_end.toordinal() + 1)
    partial = months[0] if (months[0].year, months[0].month) == (run.data_end.year, run.data_end.month) and nxt.day != 1 else None
    return Horizon(months, partial, [m for m in months if m != partial])


def item_rows(run: ForecastRun, series_names: list[str], lead_time: int = LEAD_TIME,
              service_level: float = SERVICE_LEVEL, group_id: int | None = None,
              procurement: bool = True) -> tuple[list[dict], Horizon]:
    """Строка на артикул: прогноз по месяцам и рядам, статистика спроса, запас, точка заказа."""
    hz = horizon(run)
    qs = run.items.filter(series__in=series_names)
    if group_id is not None:
        qs = qs.filter(group_id=group_id)

    acc: dict[int, dict] = {}
    for it in qs.values("item_id", "group_id", "series", "month", "qty", "revenue", "price", "price_source"):
        a = acc.get(it["item_id"])
        if a is None:
            a = acc[it["item_id"]] = {
                "item_id": it["item_id"], "group_id": it["group_id"], "price": it["price"],
                "price_source": it["price_source"], "by_month": defaultdict(float),
                "service6": 0.0, "shop6": 0.0, "revenue6": 0.0,
            }
        a["by_month"][it["month"]] += it["qty"]
        if it["month"] in hz.full[:6]:
            a[f"{it['series']}6"] += it["qty"]
            a["revenue6"] += it["revenue"]

    items = Item.objects.select_related("platform", "group").in_bulk(list(acc))
    stats = ItemDemandStats.objects.in_bulk(list(acc))
    z = z_value(service_level)
    lt_months = hz.full[:lead_time]
    rows = []
    for iid, a in acc.items():
        item, st = items.get(iid), stats.get(iid)
        if item is None:
            continue
        full6 = [a["by_month"].get(m, 0.0) for m in hz.full[:6]]
        q6 = sum(full6)
        mean_fc = q6 / len(full6) if full6 else 0.0
        q_lt = sum(a["by_month"].get(m, 0.0) for m in lt_months)
        months12 = st.months12 if st else 0
        cv = st.cv12 if st else None
        cls = demand_class(months12, cv)
        safety = z * cv * mean_fc * math.sqrt(lead_time) if procurement and cls not in ("редкий", "нет продаж") else 0.0
        if not procurement:
            rop = None
        elif cls in ("редкий", "нет продаж"):
            rop = int(math.floor(q_lt + 0.5))  # редкий: обычное округление, 0,2 шт. ≠ штука на складе
        else:
            rop = math.ceil(q_lt + safety - 1e-9)
        cost = st.last_cost if st else None
        rows.append({
            **a, "item": item, "stats": st,
            "rest": a["by_month"].get(hz.partial, 0.0) if hz.partial else 0.0,
            "months": full6, "q3": sum(full6[:3]), "q6": q6, "q_lt": q_lt,
            "cv": cv, "months12": months12, "demand": cls, "safety": safety, "rop": rop,
            "cost": cost, "rop_cost": rop * cost if (rop is not None and cost) else None,
            "price_label": PriceSource(a["price_source"]).label if a["price_source"] else "",
        })
    rows.sort(key=lambda r: -r["revenue6"])
    return rows, hz


def family_olds(ids) -> dict:
    """{актуальный номер: [старые номера]} — для раскладки по семействам (замены номеров)."""
    out = defaultdict(list)
    for head, art in (Item.objects.filter(family_head_id__in=list(ids)).order_by("article")
                      .values_list("family_head_id", "article")):
        out[head].append(art)
    return out


def series_names(series: str) -> list[str]:
    return [Series.SERVICE, Series.SHOP] if series == Series.TOTAL else [series]
