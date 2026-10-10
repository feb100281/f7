"""
На сервере: принять опубликованный снимок данных (его присылает команда publish с локальной машины).

    python manage.py apply_publish data/publish/f7_publish.sqlite3.gz

Таблицы номенклатуры, продаж, прогнозов и витрины заменяются одной транзакцией.
Пользователи, группы и права не трогаются. Отметка о публикации — data/publish/last.json.
"""

import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Принять снимок данных с локальной машины (замена таблиц одной транзакцией)"

    def add_arguments(self, parser):
        parser.add_argument("file")

    def handle(self, *args, **options):
        from core.services.publish import apply

        src = Path(options["file"])
        if not src.is_absolute():
            src = Path(settings.BASE_DIR) / src
        if not src.exists():
            raise CommandError(f"Нет файла {src}")
        try:
            result = apply(Path(settings.DATABASES["default"]["NAME"]), src, log=self.stdout.write)
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        result["published"] = time.strftime("%Y-%m-%d %H:%M:%S")
        (src.parent / "last.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Принято: снимок от {result['created']}, продажи по {result.get('data_end')}"))
