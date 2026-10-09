"""
Пересчитать товарные группы номенклатуры по правилам catalog/rules.py.

    python manage.py classify_items
Параметры задачи:
    include_manual: true — сбросить и ручную разметку менеджеров (по умолчанию false)

Нужна после правки правил: обычный импорт продаж размечает только по текущим
правилам и сам по себе тоже обновляет группы у всех артикулов без ручной разметки.
"""

from __future__ import annotations

from django.db.models import Count, Sum

from catalog.models import GroupSource, Item
from catalog.services.classify import reclassify
from core.management.base import JobCommand


class Command(JobCommand):
    help = "Пересчитать товарные группы номенклатуры по правилам (ручную разметку не трогает)"

    def run(self, params: dict):
        include_manual = bool(params.get("include_manual", False))
        if include_manual:
            self.warn("include_manual = true — ручная разметка будет сброшена на правила")

        self.step("Разметка по правилам")
        r = reclassify(include_manual=include_manual)
        self.stdout.write(f"   проверено: {r['checked']:,}, изменилось: {r['changed']:,}")

        self.step("Сводка по группам (по выручке)")
        total = Item.objects.aggregate(s=Sum("revenue"))["s"] or 1
        rows = (
            Item.objects.values("group__name")
            .annotate(n=Count("id"), rev=Sum("revenue"))
            .order_by("-rev")
        )
        for row in rows:
            share = 100 * float(row["rev"] or 0) / float(total)
            self.stdout.write(f"   {(row['group__name'] or '— без группы')[:40]:<40} {row['n']:>5} арт.  {share:>5.1f}%")

        by_source = dict(Item.objects.values_list("group_source").annotate(n=Count("id")))
        self.stdout.write(
            "   источник группы: "
            + ", ".join(f"{GroupSource(k).label}: {v:,}" for k, v in by_source.items())
        )
        self.ok("Готово")
