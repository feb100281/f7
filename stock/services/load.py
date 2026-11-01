"""
Загрузка остатков из Excel 1С в срез на дату.

Ожидается лист с шапкой: «Артикул», «Номенклатура», «Доступно», «Поступит» (порядок любой,
шапка — в первых 15 строках; синонимы: «Остаток», «В пути» и т. п.). Один артикул в нескольких
строках (две карточки в 1С) — складывается. Пустые «Доступно»/«Поступит» — 0.
Дата среза — из формы, иначе из имени файла (…16.10.2026.xlsx).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.db import transaction
from openpyxl import load_workbook

from catalog.models import Item
from forecast.models import ItemDemandStats
from stock.models import StockLine, StockSnapshot

COLUMNS = {
    "article": ("артикул",),
    "name": ("номенклатура", "наименование", "название"),
    "available": ("доступно", "свободный остаток", "остаток", "в наличии", "количество"),
    "incoming": ("поступит", "в пути", "ожидается", "ожидаемое поступление"),
}
DEAD_DAYS = 365
DATE_RX = re.compile(r"(\d{1,2})[._-](\d{1,2})[._-](\d{4})")


class StockFileError(ValueError):
    pass


def date_from_filename(name: str) -> date | None:
    m = DATE_RX.search(name or "")
    if not m:
        return None
    d, mth, y = map(int, m.groups())
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def _article(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _num(v) -> float:
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


def read_file(f) -> list[dict]:
    """[{article, name, available, incoming}] — артикулы без повторов."""
    try:
        wb = load_workbook(f, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 — не xlsx / битый файл
        raise StockFileError(f"Не получилось открыть файл как Excel (.xlsx): {e}") from e
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    cols = None
    for _ in range(15):
        head = next(rows, None)
        if head is None:
            break
        names = [str(c or "").strip().lower() for c in head]
        found = {}
        for key, variants in COLUMNS.items():
            for i, n in enumerate(names):
                if n in variants and key not in found and i not in found.values():
                    found[key] = i
        if "article" in found and "available" in found:
            cols = found
            break
    if cols is None:
        raise StockFileError("Не нашла шапку: нужны колонки «Артикул» и «Доступно» (и по желанию «Поступит»).")

    acc: dict[str, dict] = {}
    for r in rows:
        get = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None  # noqa: E731
        art = _article(get("article"))
        if not art:
            continue
        a = acc.setdefault(art, {"article": art, "name": "", "available": 0.0, "incoming": 0.0})
        a["name"] = a["name"] or str(get("name") or "").strip()[:255]
        a["available"] += _num(get("available"))
        a["incoming"] += _num(get("incoming"))
    wb.close()
    if not acc:
        raise StockFileError("В файле нет строк с артикулами.")
    return list(acc.values())


@transaction.atomic
def load(f, on_date: date, filename: str = "", user=None, note: str = "") -> tuple[StockSnapshot, bool]:
    """Загрузить файл в срез на дату. Срез на эту дату уже был — строки заменяются. → (срез, заменён ли)."""
    rows = read_file(f)
    snap = StockSnapshot.objects.filter(date=on_date).first()
    replaced = snap is not None
    if snap is None:
        snap = StockSnapshot(date=on_date)
    else:
        snap.lines.all().delete()
    snap.filename = filename or snap.filename
    snap.uploaded_by = (user.get_full_name() or user.get_username()) if getattr(user, "pk", None) else ""
    snap.note = note or snap.note
    if hasattr(f, "seek"):
        f.seek(0)
    if filename and hasattr(f, "read"):
        snap.file.save(filename, f, save=False)
    snap.save()

    items = {a: (i, ls, cost, qty) for a, i, ls, cost, qty in
             Item.objects.filter(article__in=[r["article"] for r in rows])
             .values_list("article", "id", "last_sale", "cost", "qty")}
    stats = {s.item_id: s for s in ItemDemandStats.objects.filter(item_id__in=[v[0] for v in items.values()])}
    dead_after = on_date - timedelta(days=DEAD_DAYS)

    lines, s = [], {"matched_n": 0, "available": 0.0, "incoming": 0.0, "value": 0.0, "value_known_n": 0,
                    "dead_n": 0, "dead_qty": 0.0, "dead_value": 0.0, "negative_n": 0}
    for r in rows:
        iid, last_sale, cost_total, qty_total = items.get(r["article"], (None, None, None, None))
        st = stats.get(iid)
        # с/с штуки: последняя по статистике спроса, иначе средняя за всю историю продаж
        cost = st.last_cost if st and st.last_cost else (
            float(cost_total) / float(qty_total) if qty_total and float(qty_total) > 0 and cost_total else None)
        lines.append(StockLine(snapshot=snap, item_id=iid, article=r["article"], name=r["name"],
                               available=r["available"], incoming=r["incoming"], cost=cost, last_sale=last_sale))
        s["matched_n"] += 1 if iid else 0
        s["available"] += r["available"]
        s["incoming"] += r["incoming"]
        s["negative_n"] += 1 if r["available"] < 0 else 0
        if cost and r["available"] > 0:
            s["value"] += cost * r["available"]
            s["value_known_n"] += 1
        if r["available"] > 0 and (last_sale is None or last_sale < dead_after):
            s["dead_n"] += 1
            s["dead_qty"] += r["available"]
            s["dead_value"] += (cost or 0) * r["available"]
    StockLine.objects.bulk_create(lines, batch_size=2000)
    for k, v in s.items():
        setattr(snap, k, v)
    snap.lines_n = len(lines)
    snap.order_run_id = None  # строки новые — заказ пересчитать
    snap.save()
    order_summary(snap)
    return snap, replaced


def family_position(snapshot: StockSnapshot | None) -> dict[int, tuple[float, float]]:
    """{актуальный номер: (доступно, поступит)} — остатки старых номеров сложены на актуальный."""
    if snapshot is None:
        return {}
    out: dict[int, list[float]] = {}
    for iid, head, av, inc in (snapshot.lines.exclude(item=None)
                               .values_list("item_id", "item__family_head_id", "available", "incoming")):
        a = out.setdefault(head or iid, [0.0, 0.0])
        a[0] += av
        a[1] += inc
    return {k: (v[0], v[1]) for k, v in out.items()}


def order_summary(snapshot: StockSnapshot, force: bool = False) -> StockSnapshot:
    """«К заказу» по последнему прогнозу при параметрах по умолчанию — в поля среза.
    Считается один раз на пару (срез, прогноз): рабочий стол читает готовые цифры."""
    from forecast.models import ForecastRun, Series
    from forecast.services import stock as st

    run = ForecastRun.objects.first()
    if run is None or not run.items.exists():
        return snapshot
    params = {"lt": st.LEAD_TIME, "sl": st.SERVICE_LEVEL, "rv": st.REVIEW}
    if not force and snapshot.order_run_id == run.pk and snapshot.order_params == params:
        return snapshot
    rows, _ = st.item_rows(run, st.series_names(Series.TOTAL), params["lt"], params["sl"],
                           position=family_position(snapshot), review=params["rv"])
    todo = [r for r in rows if r["order"]]
    snapshot.order_run_id = run.pk
    snapshot.order_params = params
    snapshot.order_n = len(todo)
    snapshot.order_qty = sum(r["order"] for r in todo)
    snapshot.order_cost = sum(r["order_cost"] or 0 for r in todo)
    snapshot.save(update_fields=["order_run_id", "order_params", "order_n", "order_qty", "order_cost"])
    return snapshot
