"""
Замены номеров: правила → пары «старый → новый», затем семейства (Item.family_head).

    python manage.py apply_replacements
Параметры задачи:
    rules: false — только пересобрать семейства по уже заведённым заменам

Решения менеджера (подтверждено / отклонено / заведено руками) правила не трогают.
Обычный импорт продаж запускает это сам после витрин.
"""

from __future__ import annotations

from django.db.models import Count

from catalog.models import Item, ItemReplacement, ReplacementSource, ReplacementStatus
from catalog.services.replacements import apply_rules, rebuild_families
from core.management.base import JobCommand
from core.models.jobs import JobTypes


class Command(JobCommand):
    help = "Замены номеров: X→9X, масла/химия, предложения по названию; семейства артикулов"

    job_name = "Замены номеров (семейства артикулов)"
    job_type = JobTypes.ETL
    job_description = (
        "<h2><u>Склейка номеров одного товара</u></h2>"
        "<p>Один товар под разными артикулами (779282 и 9779282, масла с одинаковыми характеристиками) "
        "собирается в семейство с актуальным номером: прогноз в штуках, статистика и «год назад» "
        "считаются по семейству. Номера в названиях — только предложения, подтверждает менеджер "
        "в «Номенклатура → Замены номеров».</p>"
        "<pre>Параметры:\nrules: false — только пересобрать семейства</pre>"
    )
    job_param = {"rules": True}

    def run(self, params: dict):
        if params.get("rules", True):
            self.step("Правила замен")
            apply_rules(log=self.stdout.write)
        self.step("Семейства")
        rebuild_families(log=self.stdout.write)

        rows = (ItemReplacement.objects.values("source", "status").annotate(n=Count("id"))
                .order_by("source", "status"))
        for r in rows:
            self.stdout.write(f"   {ReplacementSource(r['source']).label:<28} "
                              f"{ReplacementStatus(r['status']).label:<14} {r['n']:>5}")
        waiting = ItemReplacement.objects.filter(status=ReplacementStatus.SUGGESTED).count()
        if waiting:
            self.warn(f"   ждут решения менеджера: {waiting}")
        self.stdout.write(f"   артикулов в семьях: {Item.objects.exclude(family_head=None).count():,}")
        self.ok("Готово")
