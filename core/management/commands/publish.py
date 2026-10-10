"""
Опубликовать данные на сервер: локальная база — правда, сервер только показывает.

    python manage.py publish
Параметры задачи:
    host:  ssh-адрес сервера (вход по ssh-ключу, без пароля)
    path:  папка проекта на сервере
    python: python на сервере (по умолчанию .venv/bin/python в папке проекта)

Шаги: снимок таблиц данных (номенклатура, продажи, прогнозы, витрины) → gzip → scp на сервер →
на сервере `manage.py apply_publish` заменяет эти таблицы одной транзакцией.
Пользователи и права на сервере не трогаются. Перезапуск gunicorn не нужен.
"""

import shlex
import subprocess
from pathlib import Path

from django.conf import settings

from core.management.base import JobCommand
from core.models.jobs import JobTypes

REMOTE_FILE = "data/publish/f7_publish.sqlite3.gz"


class Command(JobCommand):
    help = "Опубликовать данные на сервер (снимок таблиц → scp → apply_publish на сервере)"

    job_name = "Опубликовать на сервер"
    job_type = JobTypes.PUBLISH
    job_description = (
        "<h2><u>Публикация на сервер</u></h2>"
        "<p>Отправляет на сервер номенклатуру, продажи, прогнозы и витрины — всё, что посчитано здесь. "
        "На сервере таблицы заменяются целиком одной транзакцией: пользователи видят либо старые данные, "
        "либо новые. Пользователи, группы и права на сервере свои и не трогаются. "
        "Нужен вход на сервер по ssh-ключу (без пароля) и та же версия кода на сервере (git pull + migrate).</p>"
        "<pre>Параметры:\\nhost: ssh-адрес сервера\\npath: папка проекта на сервере\\n"
        "python: python на сервере (пусто — .venv/bin/python)</pre>"
    )
    job_param = {"host": "daria@82.202.197.94", "path": "/home/daria/f7", "python": ""}

    def _run(self, cmd: list[str], what: str):
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out = (res.stdout or "").strip()
        if out:
            self.stdout.write("\n".join(f"   {line}" for line in out.splitlines()))
        if res.returncode != 0:
            err = (res.stderr or "").strip()
            hint = ""
            if "Permission denied" in err or "publickey" in err:
                hint = " — нет входа по ssh-ключу: на этой машине ssh-copy-id <host>"
            raise RuntimeError(f"{what}: {err or 'код ' + str(res.returncode)}{hint}")

    def run(self, params: dict):
        from core.services.publish import snapshot

        host = (params.get("host") or "").strip()
        path = (params.get("path") or "").rstrip("/")
        if not host or not path:
            raise ValueError("Укажите host и path в параметрах задачи")
        python = params.get("python") or f"{path}/.venv/bin/python"
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host]

        self.step("Снимок данных")
        local = Path(settings.DATA_PATH) / "publish" / "f7_publish.sqlite3.gz"
        meta = snapshot(Path(settings.DATABASES["default"]["NAME"]), local, log=self.stdout.write)
        self.stdout.write(f"   продажи по {meta.get('data_end') or '—'}")

        self.step(f"Отправка на {host}")
        self._run(ssh + [f"mkdir -p {shlex.quote(path)}/data/publish"], "Нет доступа к серверу")
        self._run(["scp", "-q", "-o", "BatchMode=yes", str(local), f"{host}:{path}/{REMOTE_FILE}"], "Не скопировалось")

        self.step("Применение на сервере")
        remote = f"cd {shlex.quote(path)} && {shlex.quote(python)} manage.py apply_publish {REMOTE_FILE}"
        self._run(ssh + [remote], "Сервер не принял данные")
        self.ok("Опубликовано")
