"""Форматирование чисел на дашбордах: {% load f7_format %} {{ value|rub }} {{ x|pct }} {{ d|delta }}."""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

NBSP = " "


def _num(value, digits=0):
    if value in (None, ""):
        return "—"
    return f"{float(value):,.{digits}f}".replace(",", NBSP)


@register.filter
def rub(value):
    """1234567 → «1 234 567»."""
    return _num(value)


@register.filter
def mln(value):
    """1234567 → «1,2 млн» (для плиток)."""
    if value in (None, ""):
        return "—"
    v = float(value)
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.1f} млн".replace(",", NBSP).replace(".", ",")
    if abs(v) >= 1e3:
        return f"{v / 1e3:,.0f} тыс.".replace(",", NBSP)
    return _num(v)


@register.filter
def num(value, digits=0):
    return _num(value, int(digits))


@register.filter
def pct(value, digits=1):
    if value in (None, ""):
        return "—"
    return f"{100 * float(value):.{int(digits)}f}%".replace(".", ",")


@register.filter
def delta(value):
    """Изменение к прошлому году: +12,3% зелёным, −4,0% красным, — если сравнивать не с чем."""
    if value in (None, ""):
        return mark_safe('<span class="f7-delta f7-delta-none">—</span>')
    v = 100 * float(value)
    cls = "f7-delta-up" if v > 0.05 else "f7-delta-down" if v < -0.05 else "f7-delta-flat"
    arrow = "▲" if v > 0.05 else "▼" if v < -0.05 else "•"
    text = f"{abs(v):.1f}%".replace(".", ",")
    return format_html('<span class="f7-delta {}">{} {}</span>', cls, arrow, text)


@register.filter
def heat(value):
    """Доля 0..1 → прозрачность красного фона для тепловой карты."""
    try:
        v = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return "transparent"
    return f"rgba(211, 20, 28, {0.06 + 0.6 * v:.2f})"
