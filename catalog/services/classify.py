"""
Автоматическая разметка артикулов: группа и техника по правилам catalog/rules.py.

Ручную разметку (group_source = manual) не трогаем никогда.
"""

from __future__ import annotations

from dataclasses import dataclass

from catalog import rules as R
from catalog.models import GroupSource, Item, ItemGroup, Platform

from .seed import ensure_groups, ensure_platforms


@dataclass
class Verdict:
    group_id: int | None
    group_source: str
    group_rule: str
    platform_id: int | None


class Classifier:
    """Кэширует справочники, чтобы размечать тысячи артикулов без лишних запросов."""

    def __init__(self):
        ensure_groups()
        ensure_platforms()
        self.groups = dict(ItemGroup.objects.values_list("code", "id"))
        self.platforms = dict(Platform.objects.values_list("code", "id"))

    def __call__(self, name: str | None, article: str | None) -> Verdict:
        code, rule = R.classify(name, article)
        if rule == "none":
            source, rule_text = GroupSource.NONE, ""
        elif rule.startswith("article:"):
            source, rule_text = GroupSource.ARTICLE, rule.split(":", 1)[1]
        else:
            source, rule_text = GroupSource.RULE, rule.split(":", 1)[1]
        return Verdict(
            group_id=self.groups.get(code) or self.groups.get("other"),
            group_source=source,
            group_rule=rule_text[:120],
            platform_id=self.platforms.get(R.platform(name, article)),
        )


def reclassify(queryset=None, include_manual: bool = False) -> dict:
    """
    Пересчитать группы по текущим правилам.
    include_manual=True — сбросить и ручную разметку (только по явной просьбе).
    """
    classify = Classifier()
    qs = queryset if queryset is not None else Item.objects.all()
    if not include_manual:
        qs = qs.exclude(group_source=GroupSource.MANUAL)

    from django.utils import timezone

    now = timezone.now()
    changed = 0
    batch = []
    for item in qs.only("id", "article", "name", "group_id", "group_source", "group_rule", "platform_id", "updated"):
        v = classify(item.name, item.article)
        if (item.group_id, item.group_source, item.group_rule, item.platform_id) != (
            v.group_id, v.group_source, v.group_rule, v.platform_id
        ):
            item.group_id, item.group_source = v.group_id, v.group_source
            item.group_rule, item.platform_id = v.group_rule, v.platform_id
            item.updated = now
            batch.append(item)
            changed += 1
    Item.objects.bulk_update(batch, ["group", "group_source", "group_rule", "platform", "updated"], batch_size=1000)
    return {"checked": qs.count(), "changed": changed}
