from django.db import models


class DemandType(models.TextChoices):
    """Тип спроса — определяет, как прогнозировать и как держать запас."""

    CONSUMABLE = "consumable", "Расходники ТО"
    WEAR = "wear", "Износ"
    REPAIR = "repair", "Ремонт"
    BODY = "body", "Кузов"
    ACCESSORY = "accessory", "Аксессуары"
    FASTENER = "fastener", "Крепёж"
    OTHER = "other", "Прочее"


class ItemGroup(models.Model):
    """
    Товарная группа запчастей. Начальный список — из catalog/rules.py (firstrun),
    дальше группы ведут менеджеры: переименовывают, добавляют свои, меняют тип спроса.
    Код группы связывает её с правилами автоматической разметки — его не меняют.
    """

    code = models.SlugField(
        verbose_name="Код",
        max_length=40,
        unique=True,
        help_text="Латиницей, без пробелов. Связывает группу с правилами разметки — после создания не меняется.",
    )
    name = models.CharField(verbose_name="Группа", max_length=120)
    demand_type = models.CharField(
        verbose_name="Тип спроса",
        max_length=20,
        choices=DemandType.choices,
        default=DemandType.OTHER,
    )
    sort = models.PositiveSmallIntegerField(verbose_name="Порядок", default=100)
    description = models.TextField(verbose_name="Описание", blank=True)

    class Meta:
        verbose_name = "Товарная группа"
        verbose_name_plural = "Товарные группы"
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name
