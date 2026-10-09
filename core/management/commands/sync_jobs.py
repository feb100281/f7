"""
Синхронизация «Списка команд» (Jobs) с кодом.

    python manage.py sync_jobs

Находит во всех приложениях management-команды на базе JobCommand с заполненным job_name
и заводит по ним карточки. Новая команда = новый файл в <app>/management/commands/ —
после git pull достаточно sync_jobs (или install.sh / firstrun, они зовут его сами).

    • новой команды нет в базе → создаётся с job_param по умолчанию;
    • команда уже есть → обновляются название, тип и описание, param НЕ трогается
      (там настройки пользователя, например папка с выгрузками);
    • в базе есть карточка, а команды в коде больше нет → только предупреждение.
"""

from django.core.management import BaseCommand, get_commands, load_command_class
from django.db import transaction

from core.management.base import JobCommand
from core.models.jobs import Jobs


def discover() -> dict[str, type[JobCommand]]:
    """{имя команды: класс} для всех JobCommand с job_name."""
    found = {}
    for name, app in sorted(get_commands().items()):
        if app.startswith("django"):
            continue
        try:
            cmd = load_command_class(app, name)
        except Exception:  # чужая команда, которая не грузится, — не наша забота
            continue
        if isinstance(cmd, JobCommand) and cmd.job_name:
            found[name] = type(cmd)
    return found


def sync_jobs(log=print) -> dict:
    found = discover()
    added = updated = 0
    with transaction.atomic():
        for name, cls in found.items():
            job, created = Jobs.objects.get_or_create(
                command=name,
                defaults={
                    "name": cls.job_name,
                    "jobtype": cls.job_type,
                    "scope": cls.job_scope,
                    "description": cls.job_description,
                    "param": dict(cls.job_param),
                },
            )
            if created:
                added += 1
                log(f"   {name}: добавлена")
                continue
            changed = []
            for field, value in (("name", cls.job_name), ("jobtype", cls.job_type),
                                 ("description", cls.job_description)):
                if getattr(job, field) != value:
                    setattr(job, field, value)
                    changed.append(field)
            if changed:
                job.save(update_fields=changed)
                updated += 1
                log(f"   {name}: обновлена ({', '.join(changed)})")

    orphans = list(Jobs.objects.exclude(command__in=found).values_list("command", flat=True))
    for name in orphans:
        log(f"   {name}: в базе есть, в коде нет — удалите карточку в админке, если команда больше не нужна")
    return {"found": len(found), "added": added, "updated": updated, "orphans": orphans}


class Command(BaseCommand):
    help = "Завести в «Списке команд» все команды JobCommand из кода"

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO("— Команды"))
        r = sync_jobs(log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(
            f"Команд в коде: {r['found']}, добавлено: {r['added']}, обновлено: {r['updated']}"
        ))
