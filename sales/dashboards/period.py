"""Фильтры дашбордов: период (месяцы), сравнение с прошлым годом, салон, канал."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
SEASON_MONTHS = ["окт", "ноя", "дек", "янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен"]

PRESETS = [
    ("12m", "Последние 12 мес."),
    ("season", "Текущий сезон"),
    ("prev_season", "Прошлый сезон"),
    ("ytd", "С начала года"),
    ("all", "Вся история"),
    ("custom", "Свой период"),
]


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def month_label(d: date) -> str:
    return f"{MONTHS_RU[d.month - 1]} {d:%y}"


def months_between(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = add_months(d, 1)
    return out


def _parse_month(value: str | None) -> date | None:
    try:
        y, m = (value or "").split("-")[:2]
        return date(int(y), int(m), 1)
    except (ValueError, TypeError):
        return None


def season_start(d: date) -> date:
    return date(d.year if d.month >= 10 else d.year - 1, 10, 1)


@dataclass
class Period:
    start: date
    end: date
    preset: str
    first: date          # первый месяц данных
    last: date           # последний месяц данных

    @property
    def months(self) -> list[date]:
        return months_between(self.start, self.end)

    @property
    def prev_start(self) -> date:
        return add_months(self.start, -12)

    @property
    def prev_end(self) -> date:
        return add_months(self.end, -12)

    @property
    def has_prev(self) -> bool:
        return self.prev_start >= self.first

    @property
    def label(self) -> str:
        if self.start == self.end:
            return month_label(self.start)
        return f"{month_label(self.start)} – {month_label(self.end)}"

    @property
    def prev_label(self) -> str:
        return f"{month_label(self.prev_start)} – {month_label(self.prev_end)}"


@dataclass
class Filters:
    period: Period
    dept: int | None = None
    kind: str | None = None
    extra: dict = field(default_factory=dict)

    def qs(self, queryset, month_field: str = "month", prev: bool = False):
        """Фильтр витрины по периоду (или тому же периоду год назад), салону и каналу."""
        start = self.period.prev_start if prev else self.period.start
        end = self.period.prev_end if prev else self.period.end
        qs = queryset.filter(**{f"{month_field}__gte": start, f"{month_field}__lte": end})
        if self.dept:
            qs = qs.filter(department_id=self.dept)
        if self.kind and "kind" in {f.name for f in queryset.model._meta.fields}:
            qs = qs.filter(kind=self.kind)
        return qs


def parse_filters(request, first: date, last: date, use_kind: bool = True) -> Filters:
    g = request.GET
    preset = g.get("period") or "12m"
    if preset == "season":
        start, end = season_start(last), last
    elif preset == "prev_season":
        s = add_months(season_start(last), -12)
        start, end = s, add_months(s, 11)
    elif preset == "ytd":
        start, end = date(last.year, 1, 1), last
    elif preset == "all":
        start, end = first, last
    elif preset == "custom":
        start = _parse_month(g.get("from")) or add_months(last, -11)
        end = _parse_month(g.get("to")) or last
    else:
        preset = "12m"
        start, end = add_months(last, -11), last

    start, end = max(start, first), min(end, last)
    if start > end:
        start, end = end, start

    try:
        dept = int(g.get("dept")) if g.get("dept") else None
    except ValueError:
        dept = None
    kind = (g.get("kind") or None) if use_kind else None
    return Filters(period=Period(start, end, preset, first, last), dept=dept, kind=kind)
