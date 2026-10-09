"""
Пересчитать витрины (DuckDB → таблицы mart_* в SQLite) и статистику артикулов.

    python manage.py build_marts

Запускается сам последним шагом импорта продаж. Руками — после массовых правок
номенклатуры, если витрина считает что-то по группам (витрины артикул × месяц
групп не хранят и в пересчёте после смены группы не нуждаются).
"""

from core.management.base import JobCommand
from marts.services.build import MARTS, build_marts, refresh_item_stats


class Command(JobCommand):
    help = "Пересчитать витрины (sql/marts/) и статистику артикулов"

    def run(self, params: dict):
        self.step(f"Витрины: {len(MARTS)} SQL-файлов")
        build_marts(log=self.stdout.write)
        self.step("Статистика в карточках артикулов")
        n = refresh_item_stats()
        self.stdout.write(f"   артикулов с продажами: {n:,}")
        self.ok("Готово")
