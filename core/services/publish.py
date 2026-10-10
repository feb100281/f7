"""
Публикация данных с локальной машины на сервер. Локальная база — правда, сервер только показывает.

    локально:  snapshot()  — таблицы данных (catalog, sales, forecast, витрины mart_*) в отдельный
                             SQLite-файл, сжатый gzip; пользователи, сессии и команды не попадают
    сервер:    apply()     — в одной транзакции заменяет эти таблицы своими копиями из файла

Таблицы Django (catalog_*, sales_*, forecast_*) не пересоздаются — схема, индексы и связи
остаются как после migrate, меняются только строки (delete + insert). Витрины mart_* — без
схемы Django, их можно пересоздать целиком. Перед заменой сверяются миграции: код на сервере
должен быть той же версии, что и локально (иначе — git pull и migrate на сервере).
Пользователи, группы и права на сервере свои — публикация их не трогает.
"""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

DATA_PREFIXES = ("catalog_", "sales_", "forecast_", "mart_")
MART_PREFIX = "mart_"
APPS = ("catalog", "sales", "forecast", "marts")


def _n(v: int) -> str:
    return f"{v:,}".replace(",", " ")


def _tables(con: sqlite3.Connection, schema: str = "main") -> list[str]:
    rows = con.execute(f"select name from {schema}.sqlite_master where type = 'table' order by name").fetchall()
    return [r[0] for r in rows if r[0].startswith(DATA_PREFIXES)]


def _columns(con: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in con.execute(f'pragma {schema}.table_info("{table}")').fetchall()]


def snapshot(db_path: Path, out_path: Path, log=print) -> dict:
    """Таблицы данных + список миграций → out_path (.sqlite3.gz). Чтение — одним снимком."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = out_path.with_suffix("")  # .sqlite3
    raw.unlink(missing_ok=True)

    con = sqlite3.connect(raw)
    con.execute("attach database ? as src", (str(db_path),))
    con.execute("begin")  # согласованный снимок источника
    tables = _tables(con, "src")
    rows = {}
    for t in tables:
        con.execute(f'create table "{t}" as select * from src."{t}"')
        rows[t] = con.execute(f'select count(*) from "{t}"').fetchone()[0]
    con.execute("create table f7_migrations as select app, name from src.django_migrations where app in "
                f"({','.join('?' * len(APPS))})", APPS)
    meta = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "tables": rows}
    try:
        meta["data_end"] = con.execute("select max(date) from src.sales_salesdoc").fetchone()[0]
    except sqlite3.Error:
        meta["data_end"] = None
    con.execute("create table f7_meta (value text)")
    con.execute("insert into f7_meta values (?)", (json.dumps(meta, ensure_ascii=False),))
    con.commit()
    con.execute("detach database src")
    con.close()

    with open(raw, "rb") as fi, gzip.open(out_path, "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo)
    raw.unlink()
    meta["size_mb"] = round(out_path.stat().st_size / 1e6, 1)
    log(f"   таблиц: {len(tables)}, строк: {_n(sum(rows.values()))}, файл {meta['size_mb']} МБ")
    return meta


def apply(db_path: Path, snapshot_gz: Path, log=print) -> dict:
    """Заменить таблицы данных в db_path содержимым снимка — одной транзакцией."""
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "publish.sqlite3"
        with gzip.open(snapshot_gz, "rb") as fi, open(snap, "wb") as fo:
            shutil.copyfileobj(fi, fo)

        con = sqlite3.connect(db_path, timeout=60, isolation_level=None)
        try:
            con.execute("attach database ? as p", (str(snap),))
            meta = json.loads(con.execute("select value from p.f7_meta").fetchone()[0])

            # версия кода: миграции данных должны совпадать
            local = set(con.execute("select app, name from p.f7_migrations").fetchall())
            server = set(con.execute(
                f"select app, name from main.django_migrations where app in ({','.join('?' * len(APPS))})", APPS
            ).fetchall())
            if local != server:
                missing = sorted(local - server)[:5]
                extra = sorted(server - local)[:5]
                raise RuntimeError(
                    "Версии не совпадают — на сервере: git pull && python manage.py migrate. "
                    f"Нет на сервере: {missing or '—'}; есть только на сервере: {extra or '—'}"
                )

            snap_tables = _tables(con, "p")
            server_tables = set(_tables(con, "main"))
            con.execute("pragma foreign_keys = off")
            con.execute("begin immediate")
            counts = {}
            for t in snap_tables:
                if t.startswith(MART_PREFIX):
                    con.execute(f'drop table if exists main."{t}"')
                    con.execute(f'create table main."{t}" as select * from p."{t}"')
                elif t in server_tables:
                    cols = [c for c in _columns(con, t, "main") if c in set(_columns(con, t, "p"))]
                    col_sql = ", ".join(f'"{c}"' for c in cols)
                    con.execute(f'delete from main."{t}"')
                    con.execute(f'insert into main."{t}" ({col_sql}) select {col_sql} from p."{t}"')
                else:
                    log(f"   пропущена {t}: нет на сервере")
                    continue
                counts[t] = con.execute(f'select count(*) from main."{t}"').fetchone()[0]
            # таблицы данных, которых в снимке нет (удалённые витрины), — очищаем
            for t in sorted(server_tables - set(snap_tables)):
                if not t.startswith(MART_PREFIX):
                    con.execute(f'delete from main."{t}"')
            bad = con.execute("pragma main.foreign_key_check").fetchall()
            if bad:
                raise RuntimeError(f"Нарушены связи в {len(bad)} строках, например {bad[0]} — публикация отменена")
            con.execute("commit")
        except Exception:
            if con.in_transaction:
                con.execute("rollback")
            raise
        finally:
            con.execute("pragma foreign_keys = on")
            con.close()

    log(f"   заменено таблиц: {len(counts)}, строк: {_n(sum(counts.values()))}")
    return {**meta, "applied": counts}
