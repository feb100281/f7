"""
Первичное наполнение базы после migrate.

    python manage.py firstrun

Что делает (можно запускать повторно — ничего не задваивает):
    1. группы пользователей (роли отдела продаж)
    2. список команд (Jobs) — параметры потом правятся в админке
    3. товарные группы и техника (catalog) — названия потом правятся в админке
"""

from django.contrib.auth.models import Group
from django.core.management import BaseCommand
from django.db import transaction

from core.models.jobs import Jobs, JobTypes, ScopeOfWorks

GROUPS = [
    "Менеджер по продажам",
    "Руководитель отдела продаж",
]

# Команды. У существующей команды param НЕ перезаписывается.
JOBS = [
    {
        "command": "parse_sales",
        "name": "Импорт продаж из 1С",
        "jobtype": JobTypes.DATA,
        "description": (
            "<h2><u>Импорт выгрузок продаж из 1С</u></h2>"
            "<p>Читает все xlsx-отчёты «Продажи» (Регистратор → Номенклатура) из папки и сверяет "
            "с «Итого» каждого файла, сырые строки и документы пишет в data/parquet/sales/. Затем: номенклатура (новые артикулы, группы по правилам, ручная "
            "разметка не трогается) → продажи в базу (полная перезаливка) → витрины (sql/marts/).</p>"
            "<pre>Параметры:\nsource: папка с выгрузками\npattern: маска файлов (*.xlsx)\n"
            "write_parquet / sync_catalog / load_sales / build_marts: false — пропустить шаг</pre>"
        ),
        "param": {
            "source": "~/Library/CloudStorage/Dropbox/Remark_app/ЛОДКИ/ДАННЫЕ",
            "pattern": "*.xlsx",
        },
    },
    {
        "command": "build_marts",
        "name": "Пересчитать витрины",
        "jobtype": JobTypes.ETL,
        "description": (
            "<h2><u>Пересчёт витрин</u></h2>"
            "<p>DuckDB выполняет SQL из папки sql/marts/ и пишет таблицы mart_* в базу: "
            "артикул × месяц × канал × подразделение, документы по месяцам (наряды), статистика артикулов. "
            "Запускается сам в конце импорта продаж. Группы в витринах не хранятся — после переноса "
            "артикулов между группами пересчёт не нужен.</p>"
            "<pre>Параметры: нет</pre>"
        ),
        "param": {},
    },
    {
        "command": "classify_items",
        "name": "Пересчитать товарные группы",
        "jobtype": JobTypes.ETL,
        "description": (
            "<h2><u>Пересчёт товарных групп по правилам</u></h2>"
            "<p>Запускать после правки правил в catalog/rules.py. Артикулы, у которых менеджер "
            "поменял группу вручную, не трогаются. Обычный импорт продаж размечает новые артикулы сам.</p>"
            "<pre>Параметры:\ninclude_manual: true — сбросить и ручную разметку (осторожно)</pre>"
        ),
        "param": {"include_manual": False},
    },
    {
        "command": "check_env",
        "name": "Проверка окружения",
        "jobtype": JobTypes.SERVICE,
        "description": (
            "<h2><u>Проверка окружения</u></h2>"
            "<p>Пишет в лог версии Python и Django, путь к базе, число таблиц и папки проекта. "
            "Удобно, чтобы убедиться, что запуск команд из админки работает.</p>"
            "<pre>Параметры: любые — будут выведены в лог</pre>"
        ),
        "param": {},
    },
    {
        "command": "clear_logs",
        "name": "Очистка логов",
        "jobtype": JobTypes.SERVICE,
        "description": (
            "<h2><u>Очистка логов команд</u></h2>"
            "<p>Оставляет в каждом логе только последние строки.</p>"
            "<pre>Параметры:\nkeep_lines: сколько строк оставить (500)</pre>"
        ),
        "param": {"keep_lines": 500},
    },
]


class Command(BaseCommand):
    help = "Первичное наполнение базы: группы пользователей, список команд"

    def handle(self, *args, **options):
        with transaction.atomic():
            self.groups()
            self.jobs()
            self.catalog()

        self.stdout.write(self.style.SUCCESS("Готово. Команды — в админке → Система → Команды."))

    # ------------------------------------------------------------------

    def step(self, text):
        self.stdout.write(self.style.HTTP_INFO(f"— {text}"))

    def groups(self):
        self.step("Группы пользователей")
        for name in GROUPS:
            Group.objects.get_or_create(name=name)

    def catalog(self):
        from catalog.services.seed import ensure_groups, ensure_platforms

        self.step("Номенклатура: товарные группы и техника")
        self.stdout.write(f"   новых групп: {ensure_groups()}, видов техники: {ensure_platforms()}")

    def jobs(self):
        self.step("Команды")
        for spec in JOBS:
            spec = dict(spec)
            command = spec.pop("command")
            job, created = Jobs.objects.get_or_create(
                command=command,
                defaults={**spec, "scope": ScopeOfWorks.LOCAL},
            )
            if not created:
                # обновляем описание, но не трогаем param (там настройки пользователя)
                job.name = spec["name"]
                job.jobtype = spec["jobtype"]
                job.description = spec["description"]
                job.save(update_fields=["name", "jobtype", "description"])
            self.stdout.write(f"   {command}: {'добавлена' if created else 'обновлена'}")
