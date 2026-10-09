"""
Графики для компонента Unfold (canvas.chart → Chart.js). Каждая функция возвращает
(data_json, options_json) — шаблон кладёт их в data-value / data-options.

Цвета: категориальная палитра, порядок фиксированный (проверена на различимость,
в том числе при дальтонизме). Каналы всегда одного цвета на всех дашбордах.
"""

from __future__ import annotations

import json

PALETTE = ["#D3141C", "#2a78d6", "#eda100", "#1baf7a", "#e87ba4", "#4a3aa7", "#eb6834", "#008300"]
MUTED = "#9ca3af"
GRID = "rgba(156,163,175,0.25)"

KIND_COLORS = {
    "service": "#D3141C",
    "sale": "#2a78d6",
    "retail": "#eda100",
    "return": MUTED,
    "correction": "#cbd5e1",
    "other": "#cbd5e1",
}


def _options(stacked: bool = False, legend: bool = True, y_suffix: str = "", horizontal: bool = False,
             y_max: float | None = None) -> dict:
    axis_val = "x" if horizontal else "y"
    axis_cat = "y" if horizontal else "x"
    opts = {
        "animation": False,
        "locale": "ru-RU",
        "responsive": True,
        "maintainAspectRatio": False,
        "indexAxis": axis_cat if horizontal else "x",
        "interaction": {"mode": "index", "intersect": False},
        "plugins": {
            "legend": {
                "display": legend, "position": "top", "align": "end",
                "labels": {"boxWidth": 8, "boxHeight": 8, "usePointStyle": True, "pointStyle": "circle", "color": MUTED},
            },
            "tooltip": {"enabled": True},
        },
        "scales": {
            axis_cat: {"stacked": stacked, "grid": {"display": False}, "ticks": {"color": MUTED, "autoSkip": True, "maxRotation": 0}},
            axis_val: {"stacked": stacked, "beginAtZero": True, "grid": {"color": GRID}, "border": {"display": False},
                       "ticks": {"color": MUTED, "maxTicksLimit": 6}},
        },
        "datasets": {"bar": {"borderRadius": 3, "maxBarThickness": 28, "borderSkipped": "start"},
                     "line": {"borderWidth": 2, "pointRadius": 0, "pointHoverRadius": 4, "tension": 0.25}},
    }
    if y_suffix:
        opts["scales"][axis_val]["title"] = {"display": True, "text": y_suffix, "color": MUTED}
    if y_max is not None:
        opts["scales"][axis_val]["max"] = y_max
    return opts


def _dump(data, opts):
    return json.dumps(data, ensure_ascii=False), json.dumps(opts, ensure_ascii=False)


def line(labels, series: list[dict], y_suffix: str = "", legend: bool = True):
    """series: [{label, data, color, dashed?}]"""
    datasets = []
    for s in series:
        ds = {
            "label": s["label"], "data": s["data"],
            "borderColor": s["color"], "backgroundColor": s["color"],
        }
        if s.get("dashed"):
            ds["borderDash"] = [5, 4]
        if s.get("fill"):
            ds["fill"] = True
            ds["backgroundColor"] = s["color"] + "22"
        datasets.append(ds)
    return _dump({"labels": labels, "datasets": datasets}, _options(legend=legend, y_suffix=y_suffix))


def bar(labels, series: list[dict], stacked: bool = False, horizontal: bool = False, y_suffix: str = "",
        legend: bool = True):
    datasets = [
        {"label": s["label"], "data": s["data"], "backgroundColor": s["color"], "borderColor": s["color"],
         "borderWidth": 0}
        for s in series
    ]
    return _dump({"labels": labels, "datasets": datasets},
                 _options(stacked=stacked, horizontal=horizontal, y_suffix=y_suffix, legend=legend))


def doughnut(labels, values, colors):
    data = {"labels": labels, "datasets": [{"data": values, "backgroundColor": colors, "borderWidth": 2,
                                            "borderColor": "rgba(255,255,255,0.9)"}]}
    opts = {
        "animation": False, "responsive": True, "maintainAspectRatio": False, "cutout": "62%",
        "plugins": {"legend": {"display": True, "position": "right",
                               "labels": {"boxWidth": 8, "boxHeight": 8, "usePointStyle": True,
                                          "pointStyle": "circle", "color": MUTED}}},
    }
    return _dump(data, opts)
