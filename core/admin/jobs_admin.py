"""
Админка «Список команд»: запуск management-команд из интерфейса и просмотр лога.
"""

from __future__ import annotations

import subprocess
import sys

from django.conf import settings
from django.contrib import admin, messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.html import escape
from unfold.decorators import action, display

from ..admins import AppModelAdmin, ChoiceBadge, FirstCol, TimeBadge
from ..models.jobs import Jobs, JobStatus, JobTypes

STATUS_BADGES = {
    JobStatus.INACTIVE: ("radio_button_unchecked", "gray"),
    JobStatus.PENDING: ("hourglass_top", "info"),
    JobStatus.RUNNING: ("progress_activity", "warning"),
    JobStatus.DONE: ("check_circle", "success"),
    JobStatus.FAILED: ("error", "danger"),
    JobStatus.CANCELED: ("block", "gray"),
}

TYPE_BADGES = {
    JobTypes.DATA: ("database", "primary"),
    JobTypes.ETL: ("calculate", "info"),
    JobTypes.PUBLISH: ("publish", "gray"),
    JobTypes.SERVICE: ("build", "gray"),
}


@admin.register(Jobs)
class JobsAdmin(AppModelAdmin):

    list_display = [
        "name_col",
        "type_col",
        "scope",
        "status_col",
        "lastrun_col",
    ]

    list_filter = [
        "jobtype",
        "scope",
        "status",
    ]

    search_fields = [
        "name",
        "command",
        "description",
    ]

    ordering = [
        "jobtype",
        "name",
    ]

    readonly_fields = [
        "status",
        "lastrun",
        "logfile",
    ]

    fieldsets = (
        (
            "Задача",
            {
                "fields": [
                    ("name", "jobtype"),
                    ("scope", "status"),
                    "description",
                ],
            },
        ),
        (
            "Выполнение",
            {
                "classes": ["tab"],
                "fields": [
                    "command",
                    "param",
                ],
            },
        ),
        (
            "Состояние",
            {
                "classes": ["tab"],
                "fields": [
                    "lastrun",
                    "logfile",
                ],
            },
        ),
    )

    # ------------------------------------------------------------------
    # Колонки
    # ------------------------------------------------------------------

    @display(description="Задача", ordering="name")
    def name_col(self, obj: Jobs):
        return FirstCol(obj.name, obj.command).name_subtext

    @display(description="Тип", ordering="jobtype")
    def type_col(self, obj: Jobs):
        return ChoiceBadge(obj, "jobtype", TYPE_BADGES).badge

    @display(description="Статус", ordering="status")
    def status_col(self, obj: Jobs):
        return ChoiceBadge(obj, "status", STATUS_BADGES).badge

    @display(description="Последний запуск", ordering="lastrun")
    def lastrun_col(self, obj: Jobs):
        return TimeBadge(obj.lastrun, empty_label="Не запускалась").related_time_badge

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    actions_row = [
        "run_command",
        "open_log",
    ]
    actions_detail = [
        "run_command_detail",
        "open_log_detail",
    ]

    def _run(self, request: HttpRequest, object_id) -> Jobs:
        job = self.get_object(request, object_id)
        if not job:
            raise Http404("Задача не найдена")

        if job.status == JobStatus.RUNNING:
            messages.warning(request, f'Задача "{job.name}" уже выполняется')
            return job

        job.status = JobStatus.PENDING
        job.save(update_fields=["status"])

        log = job.log_path
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            subprocess.Popen(
                [sys.executable, "manage.py", "run_job", str(job.id)],
                cwd=settings.BASE_DIR,
                stdout=fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        messages.success(request, f'Задача "{job.name}" запущена')
        return job

    @action(
        description="Запустить",
        permissions=["run_command"],
        url_path="run-command",
        icon="play_arrow",
    )
    def run_command(self, request: HttpRequest, object_id: int):
        self._run(request, object_id)
        # ?next=/admin/... — вернуться туда, откуда запустили (например, с дашборда)
        nxt = request.GET.get("next")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            return redirect(nxt)
        return redirect(reverse("admin:core_jobs_changelist"))

    @action(
        description="Запустить",
        permissions=["run_command"],
        url_path="run-command-detail",
        icon="play_arrow",
    )
    def run_command_detail(self, request: HttpRequest, object_id: int):
        self._run(request, object_id)
        return redirect(reverse("admin:core_jobs_change", args=[object_id]))

    def has_run_command_permission(self, request: HttpRequest, object_id=None):
        return request.user.is_superuser or request.user.has_perm("core.change_jobs")

    def _log(self, request: HttpRequest, object_id):
        job = self.get_object(request, object_id)
        if not job:
            raise Http404("Задача не найдена")

        path = job.log_path
        if not path.exists():
            raise Http404("Файл лога не найден")

        text = path.read_text(encoding="utf-8", errors="replace")
        return HttpResponse(
            "<!doctype html><meta charset='utf-8'>"
            f"<title>Лог · {escape(job.name)}</title>"
            "<body style='margin:0;background:#161A21;color:#F3F3F3'>"
            "<pre style='margin:0;padding:20px;font:12px/1.5 ui-monospace,Menlo,monospace;"
            "white-space:pre-wrap'>"
            f"{escape(text)}</pre>",
            content_type="text/html; charset=utf-8",
        )

    @action(
        description="Открыть лог",
        permissions=["open_log"],
        url_path="open-log",
        attrs={"target": "_blank"},
        icon="description",
    )
    def open_log(self, request: HttpRequest, object_id: int):
        return self._log(request, object_id)

    @action(
        description="Открыть лог",
        permissions=["open_log"],
        url_path="open-log-detail",
        attrs={"target": "_blank"},
        icon="description",
    )
    def open_log_detail(self, request: HttpRequest, object_id: int):
        return self._log(request, object_id)

    def has_open_log_permission(self, request: HttpRequest, object_id=None):
        return request.user.is_staff
