"""
Главная страница админки (DASHBOARD_CALLBACK Unfold): сводка по командам
и плитки рабочих разделов. Разделы отдела продаж добавляются сюда по мере появления.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.urls import reverse


def _jobs() -> dict:
    from core.models import Jobs, JobStatus

    qs = Jobs.objects.all()
    last = qs.exclude(lastrun=None).order_by("-lastrun").first()
    return {
        "total": qs.count(),
        "failed": qs.filter(status=JobStatus.FAILED).count(),
        "running": qs.filter(status__in=[JobStatus.RUNNING, JobStatus.PENDING]).count(),
        "last": last,
        "recent": list(qs.exclude(lastrun=None).order_by("-lastrun")[:5]),
    }


def _catalog() -> dict:
    from catalog.models import GroupSource, Item, ItemGroup

    return {
        "items": Item.objects.count(),
        "groups": ItemGroup.objects.count(),
        "unclassified": Item.objects.filter(group_source=GroupSource.NONE).count(),
        "manual": Item.objects.filter(group_source=GroupSource.MANUAL).count(),
        "regular": Item.objects.filter(months__gte=Item.REGULAR_MONTHS).count(),
    }


def dashboard_callback(request, context):
    try:
        jobs = _jobs()
    except DatabaseError:  # миграции ещё не накатаны
        jobs = {}
    try:
        catalog = _catalog()
    except DatabaseError:
        catalog = {}

    context.update({
        "jobs": jobs,
        "catalog": catalog,
        "users_count": get_user_model().objects.filter(is_active=True).count(),
        "links": {
            "jobs": reverse("admin:core_jobs_changelist"),
            "users": reverse("admin:auth_user_changelist"),
            "groups": reverse("admin:catalog_itemgroup_changelist"),
            "items": reverse("admin:catalog_item_changelist"),
            "unclassified": reverse("admin:catalog_item_changelist") + "?group_source__exact=none",
        },
        "sections": [
            ("category", "Товарные группы", "Группы запчастей: тип спроса, артикулы внутри",
             reverse("admin:catalog_itemgroup_changelist")),
            ("inventory_2", "Номенклатура", "Артикулы, продажи, смена группы",
             reverse("admin:catalog_item_changelist")),
            ("wand_shine", "Команды", "Импорт, расчёты и сервисные задачи",
             reverse("admin:core_jobs_changelist")),
            ("person_3", "Пользователи", "Менеджеры и доступы",
             reverse("admin:auth_user_changelist")),
            ("admin_panel_settings", "Роли и доступы", "Группы пользователей и права",
             reverse("admin:auth_group_changelist")),
        ],
        # Задел под следующие этапы — показываются как «скоро»
        "roadmap": [
            ("query_stats", "Прогноз спроса", "Наряды × норма, розница и реализация по группам"),
            ("checklist", "Матрица must have", "ABC × XYZ по группам и каналам"),
            ("directions_boat", "Подбор по технике", "Модель, год и серийный номер мотора → нужные детали"),
            ("warehouse", "Наличие и цены", "Остатки по салонам и прайс"),
            ("request_quote", "Заявки клиентов", "Запросы, счета и статусы"),
        ],
    })
    return context
