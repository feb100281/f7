"""
DuckDB для витрин: SQL лежит в папке sql/, в коде — только имя файла.

    from core.services.duck import Duck

    with Duck() as duck:
        duck.run("marts/item_month.sql")          # выполнить файл (несколько запросов через «;»)
        df = duck.df("marts/some_select.sql")     # результат последнего запроса → pandas

База Django (SQLite) подключена как схема `db`:
    ATTACH 'db.sqlite3' AS db (TYPE sqlite)
поэтому в SQL таблицы Django — `db.sales_salesline`, `db.catalog_item`, …, а витрины
пишутся туда же: `create table db.mart_... as select ...`. DuckDB создаёт таблицы без
внешних ключей — связи с моделями объявлены в unmanaged-моделях (db_constraint=False).

Запросы выполняются с рабочей папкой BASE_DIR — относительные пути ('data/...') работают
так же, как при запуске руками из корня проекта.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings


@contextmanager
def _in_base_dir():
    prev = os.getcwd()
    os.chdir(settings.BASE_DIR)
    try:
        yield
    finally:
        os.chdir(prev)


class Duck:
    DB_ALIAS = "db"

    def __init__(self, attach_db: bool = True):
        import duckdb

        self.con = duckdb.connect(":memory:")
        self.base: Path = Path(settings.SQL_FILES_PATH)
        if attach_db:
            sqlite_path = Path(settings.DATABASES["default"]["NAME"]).resolve()
            self.con.execute("INSTALL sqlite; LOAD sqlite;")
            self.con.execute(f"ATTACH '{sqlite_path}' AS {self.DB_ALIAS} (TYPE sqlite)")

    # ------------------------------------------------------------------

    def read(self, name: str) -> str:
        """Текст SQL-файла: read('sales/items.sql')."""
        path = self.base / name
        if not path.exists():
            raise FileNotFoundError(f"Нет SQL-файла: {path}")
        return path.read_text(encoding="utf-8")

    def _execute(self, sql: str):
        """Выполняет все запросы файла (через «;»), возвращает результат последнего."""
        return self.con.execute(sql)

    def params(self, **values) -> None:
        """Параметры для SQL-файлов: temp-таблица `params` с одной строкой.
        В SQL: `from params` / `(select run_id from params)`.

            duck.params(run_id=12, data_end=date(2026, 10, 8))
        """
        names = list(values)
        cols = ", ".join(f"? as {n}" for n in names)
        self.con.execute(f"create or replace temp table params as select {cols}", [values[n] for n in names])

    def run(self, name: str) -> None:
        with _in_base_dir():
            self._execute(self.read(name))

    def df(self, name: str):
        with _in_base_dir():
            result = self._execute(self.read(name))
            return result.df() if result is not None else None

    def close(self):
        try:
            self.con.execute(f"DETACH {self.DB_ALIAS}")
        except Exception:
            pass
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
