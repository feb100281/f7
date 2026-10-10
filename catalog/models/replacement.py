from django.db import models

from .item import Item


class ReplacementSource(models.TextChoices):
    RULE_9X = "rule9x", "Правило X → 9X"
    OIL = "oil", "Семейство масел и химии"
    NAME = "name", "Номер в названии"
    MANUAL = "manual", "Вручную"
    CLIENT = "client", "Таблица клиента"


class ReplacementStatus(models.TextChoices):
    ACTIVE = "active", "Действует"
    SUGGESTED = "suggested", "Предложено"
    REJECTED = "rejected", "Отклонено"


class ItemReplacement(models.Model):
    """
    Замена номера: старый артикул → новый (тот же товар под другим номером).

    Действующие замены склеивают артикулы в семейство: прогноз в штуках, статистика спроса
    и «год назад» считаются по всему семейству, а ставятся на актуальный номер (Item.family_head).
    Правила (catalog/services/replacements.py) только добавляют пары; решения менеджера —
    подтверждение, отклонение, ручные пары — правила не перезаписывают.
    """

    old = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="replaced_by_links",
                            verbose_name="Старый номер")
    new = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="replaces_links",
                            verbose_name="Новый номер")
    source = models.CharField("Откуда", max_length=10, choices=ReplacementSource.choices)
    status = models.CharField("Статус", max_length=10, choices=ReplacementStatus.choices,
                              default=ReplacementStatus.ACTIVE)
    note = models.CharField("Комментарий", max_length=250, blank=True)
    created = models.DateTimeField("Добавлено", auto_now_add=True)
    updated = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        verbose_name = "Замена номера"
        verbose_name_plural = "Замены номеров"
        ordering = ["status", "-updated"]
        constraints = [models.UniqueConstraint(fields=["old", "new"], name="item_replacement_uniq")]

    def __str__(self):
        return f"{self.old.article} → {self.new.article}"
