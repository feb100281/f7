"""
База для команд, которые запускаются из «Списка команд».

    class Command(JobCommand):
        help = "..."

        def run(self, params: dict):
            self.step("Делаю что-то")
            ...

Команду можно звать и руками:
    python manage.py <команда>            → параметры берутся из Jobs по имени команды
    python manage.py <команда> <job_id>   → так зовёт run_job
"""

from __future__ import annotations

from django.core.management import BaseCommand

from core.models.jobs import Jobs


class JobCommand(BaseCommand):
    job: Jobs | None = None

    def add_arguments(self, parser):
        parser.add_argument("job_id", nargs="?", type=int, default=None)

    def handle(self, *args, **options):
        job_id = options.get("job_id")
        if job_id:
            self.job = Jobs.objects.filter(pk=job_id).first()
        else:
            self.job = Jobs.objects.filter(command=self.command_name).first()

        params = (self.job.param if self.job else None) or {}
        self.run(params)

    @property
    def command_name(self) -> str:
        return self.__module__.rsplit(".", 1)[-1]

    # ------------------------------------------------------------------

    def run(self, params: dict):
        raise NotImplementedError

    def step(self, text: str):
        self.stdout.write(self.style.HTTP_INFO(f"— {text}"))

    def ok(self, text: str):
        self.stdout.write(self.style.SUCCESS(text))

    def warn(self, text: str):
        self.stdout.write(self.style.WARNING(text))
