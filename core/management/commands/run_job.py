"""
Запуск задачи из «Списка команд»:

    python manage.py run_job <job_id>

Ставит статус RUNNING → вызывает команду job.command с job_id → DONE / FAILED.
Вывод пишется в stdout; при запуске из админки он дописывается в лог задачи.
"""

import traceback

from django.core.management import BaseCommand, call_command
from django.utils import timezone

from ...models.jobs import Jobs, JobStatus


class Command(BaseCommand):
    help = "Запуск задачи из списка команд по её id"

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int)

    def handle(self, *args, **options):
        job = Jobs.objects.get(pk=options["job_id"])

        job.status = JobStatus.RUNNING
        job.lastrun = timezone.now()
        job.save(update_fields=["status", "lastrun"])

        started = timezone.localtime()
        self.stdout.write(
            "\n------------------------------------------------------------\n"
            f"СТАРТ    : {started:%Y-%m-%d %H:%M:%S}\n"
            f"Задача   : {job.name}\n"
            f"Команда  : {job.command}\n"
            f"Параметры: {job.param or {}}\n"
            "------------------------------------------------------------"
        )
        self.stdout.flush()

        try:
            call_command(job.command, job.id, stdout=self.stdout, stderr=self.stderr)
            job.status = JobStatus.DONE
            seconds = (timezone.localtime() - started).total_seconds()
            self.stdout.write(self.style.SUCCESS(f"DONE за {seconds:.1f} c"))

        except Exception:
            job.status = JobStatus.FAILED
            self.stderr.write(traceback.format_exc())
            self.stderr.write("FAILED")

        finally:
            job.save(update_fields=["status"])
