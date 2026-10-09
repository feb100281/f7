"""
Список команд (Jobs): management-команды, которые запускаются из админки.

Запуск: админка → Команды → «Запустить» → `python manage.py run_job <id>`
в отдельном процессе; вывод дописывается в media/jobs/logs/<command>.log.
"""

from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


class JobStatus(models.TextChoices):
    INACTIVE = "INACTIVE", "Не запускалась"
    PENDING = "PENDING", "Ожидает"
    RUNNING = "RUNNING", "Выполняется"
    DONE = "DONE", "Выполнено"
    FAILED = "FAILED", "Ошибка"
    CANCELED = "CANCELED", "Отменено"


class ScopeOfWorks(models.TextChoices):
    SERVER = "SERVER", "Сервер"
    LOCAL = "LOCAL", "Локалка"
    LOCSER = "LOCSER", "Локалка / Сервер"


class JobTypes(models.TextChoices):
    DATA = "DATA", "Данные и импорт"
    ETL = "ETL", "Расчёты"
    PUBLISH = "PUBLISH", "Обновления"
    SERVICE = "SERVICE", "Сервис"


class Jobs(models.Model):
    jobtype = models.CharField(
        verbose_name="Тип задачи",
        max_length=20,
        choices=JobTypes.choices,
        default=JobTypes.DATA,
    )

    name = models.CharField(
        verbose_name="Задача",
        max_length=250,
    )

    command = models.CharField(
        verbose_name="Команда",
        max_length=250,
        unique=True,
        help_text="Имя management-команды: python manage.py <команда> <id задачи>",
    )

    description = models.TextField(
        verbose_name="Описание",
        blank=True,
    )

    scope = models.CharField(
        verbose_name="Область",
        max_length=20,
        choices=ScopeOfWorks.choices,
        default=ScopeOfWorks.LOCAL,
    )

    param = models.JSONField(
        verbose_name="Параметры",
        default=dict,
        blank=True,
    )

    status = models.CharField(
        verbose_name="Статус",
        max_length=20,
        choices=JobStatus.choices,
        default=JobStatus.INACTIVE,
    )

    lastrun = models.DateTimeField(
        verbose_name="Последний запуск",
        null=True,
        blank=True,
    )

    logfile = models.FileField(
        verbose_name="Файл лога",
        upload_to="jobs/logs/",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Команда"
        verbose_name_plural = "Список команд"
        ordering = ["jobtype", "name"]

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------

    @property
    def log_relative_path(self) -> Path:
        return Path("jobs") / "logs" / f"{self.command}.log"

    @property
    def log_path(self) -> Path:
        return Path(settings.MEDIA_ROOT) / self.log_relative_path

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        absolute_path = self.log_path
        if not absolute_path.exists():
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            created = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
            absolute_path.write_text(
                "============================================================\n"
                f"JOB      : {self.command}\n"
                f"CREATED  : {created}\n"
                "============================================================\n\n",
                encoding="utf-8",
            )

        relative = str(self.log_relative_path)
        if self.logfile.name != relative:
            self.logfile.name = relative
            super().save(update_fields=["logfile"])
