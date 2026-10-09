"""
Пересчитать витрины (DuckDB → таблицы mart_* в SQLite) и статистику артикулов.

    python manage.py build_marts

Запускается сам последним шагом импорта продаж. Руками — после переноса артикулов
между группами: группа в витринах записана на момент пересчёта.
"""

from core.management.base import JobCommand
from core.models.jobs import JobTypes
from marts.services.build import MARTS, build_marts, refresh_item_stats


class Command(JobCommand):
    help = "Пересчитать витрины (sql/marts/) и статистику артикулов"

    job_name = "Пересчитать витрины"
    job_type = JobTypes.ETL
    job_description = (
        "<h2><u>Пересчёт витрин для дашбордов</u></h2>"
        "<p>DuckDB выполняет SQL из папки sql/marts/ и пишет таблицы mart_* в базу: продажи, "
        "товарные группы, наряды, сезонность, артикул × месяц, статистика артикулов. "
        "Запускается сам в конце импорта продаж. Руками — после переноса артикулов между "
        "группами (дашборд покажет «витрины устарели»).</p>"
        "<pre>Параметры: нет</pre>"
    )

    def run(self, params: dict):
        self.step(f"Витрины: {len(MARTS)} SQL-файлов")
        build_marts(log=self.stdout.write)
        self.step("Статистика в карточках артикулов")
        n = refresh_item_stats()
        self.stdout.write(f"   артикулов с продажами: {n:,}")
        self.ok("Готово")
