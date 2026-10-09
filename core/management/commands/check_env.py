"""
Проверка окружения — пробная команда, чтобы убедиться, что запуск из админки работает.

    python manage.py check_env
"""

import platform
import sys

import django
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection

from core.management.base import JobCommand
from core.models import Jobs


class Command(JobCommand):
    help = "Проверка окружения: Python, Django, база, папки"

    def run(self, params: dict):
        self.step("Окружение")
        self.stdout.write(f"   Python : {sys.version.split()[0]} ({platform.platform()})")
        self.stdout.write(f"   Django : {django.get_version()}")
        self.stdout.write(f"   Проект : {settings.BASE_DIR}")

        self.step("База данных")
        db = settings.DATABASES["default"]
        self.stdout.write(f"   {connection.vendor}: {db['NAME']}")
        self.stdout.write(f"   таблиц : {len(connection.introspection.table_names())}")
        self.stdout.write(f"   пользователей: {get_user_model().objects.count()}, команд: {Jobs.objects.count()}")

        self.step("Папки")
        for name in ("MEDIA_ROOT", "DATA_PATH"):
            path = getattr(settings, name)
            mark = "есть" if path.exists() else "нет (будет создана при первой записи)"
            self.stdout.write(f"   {name}: {path} — {mark}")

        if params:
            self.step("Параметры задачи")
            for key, value in params.items():
                self.stdout.write(f"   {key}: {value}")

        self.ok("Окружение в порядке")
