"""
Первичное наполнение базы после migrate.

    python manage.py firstrun

Что делает (можно запускать повторно — ничего не задваивает):
    1. группы пользователей (роли отдела продаж)
    2. список команд (Jobs) — sync_jobs: все команды JobCommand из кода, param не перезаписывается
    3. товарные группы и техника (catalog) — названия потом правятся в админке
"""

from django.contrib.auth.models import Group
from django.core.management import BaseCommand
from django.db import transaction

GROUPS = [
    "Менеджер по продажам",
    "Руководитель отдела продаж",
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
        from core.management.commands.sync_jobs import sync_jobs

        self.step("Команды (все JobCommand из кода, см. sync_jobs)")
        sync_jobs(log=self.stdout.write)
