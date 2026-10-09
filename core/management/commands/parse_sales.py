"""
Импорт выгрузок продаж из 1С (отчёт «Продажи» с группировкой Регистратор → Номенклатура)
в базу: номенклатура, документы и строки продаж, витрины.

    python manage.py parse_sales
Параметры задачи:
    source:  папка с xlsx-выгрузками (вложенные папки тоже читаются)
    pattern: маска файлов, по умолчанию "*.xlsx"

Формат исходника (лист 1):
    шапка    — «Период отчета: …», «Отбор: …»
    заголовок — Регистратор / Номенклатура | Номенклатура.Артикул | Группа аналитического учета |
                Количество | Сумма выручки с НДС | Стоимость
    строки   — «<вид документа> <номер> от <дата время>» с итогами по документу,
               под ним строки номенклатуры (у них заполнен артикул), в конце «Итого».

Шаги:
    1. xlsx → строки продаж и документы (pandas), сверка с «Итого» каждого файла;
       сырые данные — в data/parquet/sales/sales_lines.parquet и sales_docs.parquet
       (для разбора руками в DuckDB). Отключается: "write_parquet": false
    2. номенклатура (catalog.Item): новые артикулы, названия, группы по правилам —
       ручная разметка менеджеров не трогается. Отключается: "sync_catalog": false
    3. продажи в базу (sales): документы и строки со ссылкой на артикул — полная перезаливка.
       Отключается: "load_sales": false
    4. витрины (DuckDB, sql/marts/ → таблицы mart_* в SQLite) и статистика артикулов.
       Отключается: "build_marts": false
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from django.conf import settings

from core.management.base import JobCommand

DOC_RE = re.compile(
    r"^(?P<type>.+?)\s+(?P<number>\S+)\s+от\s+"
    r"(?P<dt>\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}:\d{2})\s*$"
)
PERIOD_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})")
TRAILING_ARTICLE_RE = re.compile(r"\s*\(([^()]*)\)\s*$")

DOC_KINDS = {
    "Реализация товаров и услуг": "sale",
    "Реализация товаров и услуг (Наряд)": "service",
    "Отчет о розничных продажах": "retail",
    "Возврат товаров от клиента": "return",
    "Отчет о розничных возвратах": "return",
    "Корректировка реализации": "correction",
}

# заголовки колонок → наши поля
HEADERS = {
    "Номенклатура.Артикул": "article",
    "Группа аналитического учета": "group",
    "Количество": "qty",
    "Сумма выручки с НДС": "revenue",
    "Стоимость": "cost",
}


class Command(JobCommand):
    help = "Выгрузки продаж 1С (xlsx) → номенклатура, продажи и витрины в базе"

    def run(self, params: dict):
        import pandas as pd

        source = Path(str(params.get("source") or "")).expanduser()
        pattern = params.get("pattern") or "*.xlsx"
        if not str(source) or not source.is_dir():
            raise ValueError(f"Папка не найдена: '{source}'. Укажите source в параметрах задачи.")

        files = sorted(
            f for f in source.rglob(pattern)
            if f.is_file() and not f.name.startswith(("~$", "."))
        )
        if not files:
            raise ValueError(f"В папке {source} нет файлов {pattern}")

        self.step(f"Папка: {source}, файлов: {len(files)}")

        lines, docs = [], []
        for path in files:
            file_lines, file_docs = self.parse_file(path, source)
            lines += file_lines
            docs += file_docs

        lines_df = pd.DataFrame(lines)
        docs_df = pd.DataFrame(docs)

        lines_df, docs_df = self.drop_duplicate_docs(lines_df, docs_df)
        lines_df, docs_df = self.typed(lines_df, docs_df)

        self.summary(lines_df, docs_df)

        if params.get("write_parquet", True):
            self.write_parquet(lines_df, docs_df)
        if params.get("sync_catalog", True):
            self.sync_catalog(lines_df)
        if params.get("load_sales", True):
            self.load_sales(lines_df, docs_df)
        if params.get("build_marts", True):
            self.build_marts()
        self.ok("Готово")

    # ------------------------------------------------------------------
    # Витрины (SQL) и номенклатура
    # ------------------------------------------------------------------

    def write_parquet(self, lines_df, docs_df):
        out = Path(settings.PARQUET_FILES_PATH) / "sales"
        out.mkdir(parents=True, exist_ok=True)
        self.step(f"Parquet → {out}")
        for name, df in (("sales_lines", lines_df), ("sales_docs", docs_df)):
            df.to_parquet(out / f"{name}.parquet", index=False)
            self.stdout.write(f"   {name}.parquet: {len(df):,} строк")

    def build_marts(self):
        from marts.services.build import build_marts, refresh_item_stats

        self.step("Витрины (DuckDB → mart_* в базе)")
        build_marts(log=self.stdout.write)
        n = refresh_item_stats()
        self.stdout.write(f"   статистика артикулов обновлена: {n:,}")

    def load_sales(self, lines_df, docs_df):
        from sales.services.load import load_sales

        self.step("Продажи → база (полная перезаливка)")
        r = load_sales(lines_df, docs_df)
        self.stdout.write(
            f"   документов: {r['docs']:,}, строк: {r['lines']:,}, подразделений: {r['departments']}"
            + (f", новых артикулов: {r['new_items']}" if r["new_items"] else "")
        )
        if r["skipped"]:
            self.warn(f"   строк без документа пропущено: {r['skipped']:,}")

    def sync_catalog(self, lines_df):
        from catalog.services.sync import sync_items

        self.step("Номенклатура → база")
        r = sync_items(lines_df)
        self.stdout.write(
            f"   артикулов в выгрузке: {r['rows']:,}, новых: {r['created']:,}, обновлено: {r['updated']:,}, "
            f"с ручной группой (группа не тронута): {r['manual_kept']:,}"
        )
        if r["unclassified"]:
            self.warn(f"   без группы (не распознаны правилами): {r['unclassified']:,} — разметить в админке")

    # ------------------------------------------------------------------
    # Разбор одного файла
    # ------------------------------------------------------------------

    def parse_file(self, path: Path, root: Path):
        from openpyxl import load_workbook

        rel = str(path.relative_to(root))
        self.step(f"Файл: {rel}")

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        period_from = period_to = None
        selection = None
        header_row = None
        cols: dict[str, int] = {}

        # --- шапка и заголовок таблицы
        for i, row in enumerate(rows[:30]):
            cells = [c for c in row]
            text = " ".join(str(c) for c in cells if c is not None)
            if text.startswith("Параметры:"):
                m = PERIOD_RE.search(text)
                if m:
                    period_from = datetime.strptime(m.group(1), "%d.%m.%Y").date()
                    period_to = datetime.strptime(m.group(2), "%d.%m.%Y").date()
            if text.startswith("Отбор:"):
                selection = text.removeprefix("Отбор:").strip()
            for j, c in enumerate(cells):
                if isinstance(c, str) and c.strip() in HEADERS:
                    cols[HEADERS[c.strip()]] = j
            if cells and cells[0] == "Номенклатура" and "qty" in cols:
                header_row = i
                break

        missing = {"article", "qty", "revenue", "cost"} - set(cols)
        if header_row is None or missing:
            raise ValueError(f"{rel}: не нашёл заголовок таблицы (нет колонок: {missing or 'Номенклатура'})")

        def val(row, key):
            j = cols.get(key)
            return row[j] if j is not None and j < len(row) else None

        lines, docs = [], []
        doc = None
        line_no = 0
        total = None
        skipped = []

        for i, row in enumerate(rows[header_row + 1:], start=header_row + 2):
            first = row[0] if row else None
            if first is None or (isinstance(first, str) and not first.strip()):
                continue
            first = str(first).strip()
            article = val(row, "article")

            if first == "Итого" and article in (None, ""):
                total = {k: val(row, k) for k in ("qty", "revenue", "cost")}
                continue

            if article not in (None, ""):
                if doc is None:
                    skipped.append((i, first))
                    continue
                line_no += 1
                lines.append({
                    **{k: doc[k] for k in (
                        "source_file", "doc_type", "doc_kind", "doc_number",
                        "doc_prefix", "doc_dt",
                    )},
                    "line_no": line_no,
                    "src_row": i,
                    "article": str(article).strip(),
                    "name_1c": first,
                    "name": TRAILING_ARTICLE_RE.sub("", first).strip() or first,
                    "group": val(row, "group"),
                    "qty": val(row, "qty"),
                    "revenue": val(row, "revenue"),
                    "cost": val(row, "cost"),
                })
                continue

            m = DOC_RE.match(first)
            if m:
                doc_type = m["type"].strip()
                number = m["number"]
                doc = {
                    "source_file": rel,
                    "src_row": i,
                    "doc_type": doc_type,
                    "doc_kind": DOC_KINDS.get(doc_type, "other"),
                    "doc_number": number,
                    "doc_prefix": number.split("-")[0] if "-" in number else "",
                    "doc_dt": datetime.strptime(m["dt"], "%d.%m.%Y %H:%M:%S"),
                    "qty": val(row, "qty"),
                    "revenue": val(row, "revenue"),
                    "cost": val(row, "cost"),
                    "period_from": period_from,
                    "period_to": period_to,
                    "selection": selection,
                }
                docs.append(doc)
                line_no = 0
                continue

            skipped.append((i, first))

        # --- сверка с «Итого»
        self.stdout.write(
            f"   период {period_from:%d.%m.%Y} – {period_to:%d.%m.%Y}, "
            f"документов: {len(docs):,}, строк: {len(lines):,}"
            if period_from else f"   документов: {len(docs):,}, строк: {len(lines):,}"
        )
        if total:
            for key, label in (("qty", "кол-во"), ("revenue", "выручка"), ("cost", "стоимость")):
                ours = sum(float(r[key] or 0) for r in lines)
                theirs = float(total[key] or 0)
                mark = "ок" if abs(ours - theirs) < 0.5 else f"РАСХОЖДЕНИЕ {ours - theirs:,.2f}"
                self.stdout.write(f"   Итого {label}: {theirs:,.2f} — {mark}")
        else:
            self.warn("   строки «Итого» нет — сверку пропускаю")
        if skipped:
            self.warn(f"   пропущено нераспознанных строк: {len(skipped)}, первые: {skipped[:5]}")

        return lines, docs

    # ------------------------------------------------------------------
    # Чистка и типы
    # ------------------------------------------------------------------

    def drop_duplicate_docs(self, lines_df, docs_df):
        """Если выгрузки пересекаются по периоду — документ берём из первого файла."""
        key = ["doc_type", "doc_number", "doc_dt"]
        first_file = docs_df.drop_duplicates(key)[key + ["source_file"]]
        dups = len(docs_df) - len(first_file)
        if dups:
            self.warn(f"   документов в нескольких файлах: {dups} — оставляю первое вхождение")
            docs_df = docs_df.merge(first_file, on=key + ["source_file"])
            lines_df = lines_df.merge(first_file, on=key + ["source_file"])
        return lines_df, docs_df

    def typed(self, lines_df, docs_df):
        import pandas as pd

        for df in (lines_df, docs_df):
            for col in ("qty", "revenue", "cost"):
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
            df["doc_dt"] = pd.to_datetime(df["doc_dt"])
            df["date"] = df["doc_dt"].dt.normalize()
            for col in ("source_file", "doc_type", "doc_kind", "doc_number", "doc_prefix"):
                df[col] = df[col].astype("string")

        lines_df["margin"] = lines_df["revenue"] - lines_df["cost"]
        lines_df["is_return"] = lines_df["doc_kind"].eq("return") | lines_df["qty"].lt(0)
        for col in ("article", "name_1c", "name", "group"):
            lines_df[col] = lines_df[col].astype("string")
        lines_df["line_no"] = lines_df["line_no"].astype("int32")
        lines_df["src_row"] = lines_df["src_row"].astype("int32")

        n_lines = lines_df.groupby(["source_file", "doc_type", "doc_number", "doc_dt"]).size()
        docs_df = docs_df.merge(
            n_lines.rename("lines").reset_index(),
            on=["source_file", "doc_type", "doc_number", "doc_dt"],
            how="left",
        )
        docs_df["lines"] = docs_df["lines"].fillna(0).astype("int32")
        docs_df["src_row"] = docs_df["src_row"].astype("int32")
        docs_df["period_from"] = pd.to_datetime(docs_df["period_from"])
        docs_df["period_to"] = pd.to_datetime(docs_df["period_to"])
        docs_df["selection"] = docs_df["selection"].astype("string")

        lines_df = lines_df.sort_values(["doc_dt", "doc_number", "line_no"], ignore_index=True)
        docs_df = docs_df.sort_values(["doc_dt", "doc_number"], ignore_index=True)

        line_cols = [
            "date", "doc_dt", "doc_kind", "doc_type", "doc_number", "doc_prefix", "line_no",
            "article", "name", "group", "qty", "revenue", "cost", "margin", "is_return",
            "name_1c", "source_file", "src_row",
        ]
        doc_cols = [
            "date", "doc_dt", "doc_kind", "doc_type", "doc_number", "doc_prefix",
            "qty", "revenue", "cost", "lines", "source_file", "src_row",
            "period_from", "period_to", "selection",
        ]
        return lines_df[line_cols], docs_df[doc_cols]

    # ------------------------------------------------------------------

    def summary(self, lines_df, docs_df):
        self.step("Сводка")
        self.stdout.write(
            f"   период: {lines_df['date'].min():%d.%m.%Y} – {lines_df['date'].max():%d.%m.%Y}, "
            f"артикулов: {lines_df['article'].nunique():,}, документов: {len(docs_df):,}"
        )
        by_kind = lines_df.groupby("doc_kind")[["qty", "revenue"]].sum()
        for kind, r in by_kind.iterrows():
            self.stdout.write(f"   {kind:<11} кол-во {r['qty']:>12,.1f}   выручка {r['revenue']:>16,.0f}")
        by_prefix = docs_df.groupby("doc_prefix").size().sort_values(ascending=False)
        self.stdout.write("   префиксы номеров (подразделения): " + ", ".join(f"{k}: {v}" for k, v in by_prefix.items()))
        no_rev = int(lines_df["revenue"].isna().sum())
        no_cost = int(lines_df["cost"].isna().sum())
        if no_rev or no_cost:
            self.stdout.write(f"   строк без выручки: {no_rev:,}, без стоимости: {no_cost:,}")
