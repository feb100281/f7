"""
Главная страница админки (DASHBOARD_CALLBACK Unfold): сводка продаж и прогноза со ссылками
на дашборды, последние обновления и изменения, кто заходил, рабочие разделы.

Команды и прочая «кухня» сюда не выводятся — это не для менеджеров (они в «Системе»).
Каждый блок считается отдельно и не роняет страницу, если его данных ещё нет.
"""

from __future__ import annotations

from datetime import date, datetime

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone


def _safe(fn, default=None):
    try:
        return fn()
    except DatabaseError:  # миграции не накатаны или витрины ещё не построены
        return default


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _sales() -> dict | None:
    """Выручка, наряды и сезонность — тем же кодом, что и дашборды, с их фильтрами по умолчанию."""
    from marts.models import MartMeta
    from sales.dashboards.period import SEASON_MONTHS
    from sales.dashboards.views import home_figures

    meta = MartMeta.objects.first()
    fig = home_figures() if meta else None
    if not fig:
        return None
    last_date = _d(meta.last_date)
    fig["last_date"] = last_date
    fig["built"] = datetime.fromtimestamp(meta.built_at, tz=timezone.get_current_timezone())

    cur_sm = (last_date.month + 2) % 12 + 1          # месяц сезона: октябрь = 1
    rows = []
    for s in fig["seasons"]:
        avg = s["avg"]
        mx = max(avg) or 1
        peak = avg.index(max(avg))
        rows.append({
            "label": s["label"], "url": s["url"], "n": s["n"],
            "peak": SEASON_MONTHS[peak], "peak_share": avg[peak], "now_share": avg[cur_sm - 1],
            "next3": round(sum(avg[(cur_sm + i) % 12] for i in range(3)), 1),
            "bars": [{"m": SEASON_MONTHS[i], "share": v, "h": round(100 * v / mx), "now": i == cur_sm - 1}
                     for i, v in enumerate(avg)],
        })
    fig["season"] = {"rows": rows, "now": SEASON_MONTHS[cur_sm - 1]} if rows else None
    return fig


def _forecast() -> dict | None:
    from forecast.models import ForecastRun, Series
    from forecast.views import _accuracy

    run = ForecastRun.objects.first()
    if not run:
        return None
    points = list(run.points.filter(series=Series.TOTAL).order_by("month"))
    full = [p for p in points if not p.actual_before][:6]
    acc = _accuracy(Series.TOTAL)
    return {
        "run": run,
        "sum6": sum(p.expected for p in full),
        "period": f"{full[0].month:%m.%Y} – {full[-1].month:%m.%Y}" if full else "",
        "error6": acc["sum6"] if acc else None,
    }


def _catalog() -> dict:
    from catalog.models import Item, ItemGroup

    other = ItemGroup.objects.filter(code="other").first()
    return {
        "items": Item.objects.count(),
        "groups": ItemGroup.objects.count(),
        "unknown": Item.objects.filter(group__isnull=True).count()
                   + (Item.objects.filter(group=other).count() if other else 0),
        "other_id": other.pk if other else None,
    }


def _updates(sales, forecast) -> list[dict]:
    """Лента: когда обновлялись данные и прогноз, что меняли руками в админке."""
    events = []
    if sales:
        events.append({"when": sales["built"], "icon": "database", "who": None,
                       "text": f"Продажи и витрины обновлены — данные по {sales['last_date']:%d.%m.%Y}",
                       "url": reverse("sales_dashboard_overview")})
    if forecast:
        run = forecast["run"]
        events.append({"when": run.created, "icon": "trending_up", "who": None,
                       "text": f"Построен прогноз по данным на {run.data_end:%d.%m.%Y}",
                       "url": reverse("forecast_dashboard_overview")})
    for e in LogEntry.objects.select_related("user", "content_type").order_by("-action_time")[:8]:
        verb = {1: "добавил", 2: "изменил", 3: "удалил"}.get(e.action_flag, "изменил")
        what = e.content_type.name if e.content_type else ""
        url = None
        if e.action_flag != 3 and e.content_type:
            try:
                url = reverse(f"admin:{e.content_type.app_label}_{e.content_type.model}_change", args=[e.object_id])
            except Exception:
                url = None
        events.append({"when": e.action_time, "icon": "edit", "url": url,
                       "who": e.user.get_full_name() or e.user.username,
                       "text": f"{verb} {what.lower()}: {e.object_repr}"})
    events.sort(key=lambda x: x["when"], reverse=True)
    return events[:8]


def _visitors() -> list:
    return list(get_user_model().objects.filter(is_active=True, last_login__isnull=False)
                .order_by("-last_login")[:6])


def dashboard_callback(request, context):
    sales = _safe(_sales)
    forecast = _safe(_forecast)
    season = sales["season"] if sales else None
    links = {
        "overview": reverse("sales_dashboard_overview"),
        "service": reverse("sales_dashboard_service"),
        "groups_dash": reverse("sales_dashboard_groups"),
        "season": reverse("sales_dashboard_season"),
        "forecast": reverse("forecast_dashboard_overview"),
        "order": reverse("forecast_dashboard_qty"),
        "groups": reverse("admin:catalog_itemgroup_changelist"),
        "items": reverse("admin:catalog_item_changelist"),
    }
    catalog = _safe(_catalog, {})
    if catalog.get("other_id"):
        links["unknown"] = f"{links['items']}?group__id__exact={catalog['other_id']}"

    context.update({
        "sales": sales,
        "forecast": forecast,
        "season": season,
        "catalog": catalog,
        "updates": _safe(lambda: _updates(sales, forecast), []),
        "visitors": _safe(_visitors, []),
        "links": links,
        "sections": [
            ("monitoring", "Продажи", "Выручка, маржа и каналы с сравнением к прошлому году", links["overview"]),
            ("build", "Сервис (наряды)", "Число нарядов, что в них уходит, норма на 100 нарядов", links["service"]),
            ("calendar_month", "Сезонность", "Профиль сезона и пики по товарным группам", links["season"]),
            ("trending_up", "Прогноз выручки", "Сервис и продажи на 6 месяцев, проверка на прошлых сезонах",
             links["forecast"]),
            ("inventory_2", "Расчёт заказа", "Прогноз в штуках, страховой запас, точка заказа, выгрузка в Excel",
             links["order"]),
            ("category", "Товарные группы", "Группы запчастей: разметка, артикулы внутри", links["groups"]),
            ("list_alt", "Номенклатура", "Артикулы, продажи, смена группы", links["items"]),
        ],
        "roadmap": [
            ("menu_book", "Цифровые каталоги", "Схемы и номера деталей по технике"),
            ("warehouse", "Остатки", "Склад и салоны — сравнение с точкой заказа"),
            ("autorenew", "Анализ оборачиваемости", "Сколько дней лежит запас, что залежалось"),
            ("send", "Telegram-бот", "Прогноз, точка заказа и продажи по артикулу — прямо в Telegram"),
            ("smart_toy", "ИИ-помощник", "Вопросы по продажам и прогнозу обычным языком"),
        ],
        "help_tips": [
            ("tune", "Фильтры сверху", "период, салон и канал — сравнение всегда с тем же периодом год назад"),
            ("touch_app", "Клик по строке", "группа → её артикулы, артикул → его карточка"),
            ("info", "Пунктир у заголовка", "наведите — появится пояснение, что значит колонка"),
            ("download", "Выгрузить в Excel", "на «Расчёте заказа»: срок поставки меняется прямо в файле"),
        ],
    })
    return context
