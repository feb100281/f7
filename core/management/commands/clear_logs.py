"""
Очистка логов команд: оставляет в каждом логе последние N строк.

    python manage.py clear_logs
Параметры задачи: {"keep_lines": 500}
"""

from core.management.base import JobCommand
from core.models import Jobs


class Command(JobCommand):
    help = "Обрезать логи команд до последних N строк"

    def run(self, params: dict):
        keep = int(params.get("keep_lines", 500))
        self.step(f"Обрезаю логи до {keep} строк")

        for job in Jobs.objects.all():
            path = job.log_path
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            if len(lines) > keep:
                path.write_text("".join(lines[-keep:]), encoding="utf-8")
                self.stdout.write(f"   {job.command}: {len(lines)} → {keep}")

        self.ok("Готово")
