from django.db import models

from .group import ItemGroup
from .platform import Platform


class GroupSource(models.TextChoices):
    """Чем определена группа артикула. Ручную разметку автоматика никогда не перезаписывает."""

    RULE = "rule", "Правило по названию"
    ARTICLE = "article", "Префикс артикула"
    MANUAL = "manual", "Вручную"
    NONE = "none", "Не распознано"


class Item(models.Model):
    """
    Номенклатура — артикул запчасти.

    Заполняется командой «Продажи из 1С → parquet»: новые артикулы добавляются,
    у существующих обновляются название и статистика продаж. Группа ставится
    правилами (catalog/rules.py), пока менеджер не поменяет её руками.
    """

    article = models.CharField(verbose_name="Артикул", max_length=40, unique=True)
    name = models.CharField(verbose_name="Название", max_length=255, help_text="Без артикула в скобках")
    name_1c = models.CharField(verbose_name="Название в 1С", max_length=255, blank=True)

    group = models.ForeignKey(
        ItemGroup,
        verbose_name="Группа",
        on_delete=models.PROTECT,
        related_name="items",
        null=True,
        blank=True,
    )
    group_source = models.CharField(
        verbose_name="Чем определена группа",
        max_length=10,
        choices=GroupSource.choices,
        default=GroupSource.NONE,
    )
    group_rule = models.CharField(
        verbose_name="Сработавшее правило",
        max_length=120,
        blank=True,
        help_text="Слово из названия или префикс артикула, по которым выбрана группа",
    )
    platform = models.ForeignKey(
        Platform,
        verbose_name="Техника",
        on_delete=models.SET_NULL,
        related_name="items",
        null=True,
        blank=True,
    )

    # --- статистика продаж (пересчитывается при каждом импорте)
    first_sale = models.DateField(verbose_name="Первая продажа", null=True, blank=True)
    last_sale = models.DateField(verbose_name="Последняя продажа", null=True, blank=True)
    qty = models.DecimalField(verbose_name="Кол-во", max_digits=14, decimal_places=3, default=0)
    revenue = models.DecimalField(verbose_name="Выручка с НДС", max_digits=16, decimal_places=2, default=0)
    cost = models.DecimalField(verbose_name="Себестоимость", max_digits=16, decimal_places=2, default=0)
    docs = models.PositiveIntegerField(verbose_name="Документов", default=0)
    months = models.PositiveSmallIntegerField(
        verbose_name="Месяцев с продажами", default=0,
        help_text="В скольких календарных месяцах артикул продавался",
    )

    family_head = models.ForeignKey(
        "self", verbose_name="Актуальный номер", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="family_members",
        help_text="Заполняется сам по заменам номеров: на какой артикул переходят прогноз и статистика",
    )

    is_new = models.BooleanField(
        verbose_name="Новинка", default=False,
        help_text="Первая продажа (по всему семейству номеров) — за последние 6 месяцев. "
                  "Короткая история: прогноз и запас проверять вручную. Ставится само при импорте",
    )
    new_since = models.DateField(verbose_name="Продаётся с", null=True, blank=True,
                                 help_text="Первая продажа семейства — для новинок")

    note = models.TextField(verbose_name="Комментарий", blank=True)
    created = models.DateTimeField(verbose_name="Добавлен", auto_now_add=True)
    updated = models.DateTimeField(verbose_name="Обновлён", auto_now=True)

    REGULAR_MONTHS = 24

    class Meta:
        verbose_name = "Артикул"
        verbose_name_plural = "Номенклатура"
        ordering = ["-revenue"]
        indexes = [
            models.Index(fields=["group", "-revenue"]),
            models.Index(fields=["group_source"]),
        ]

    def __str__(self):
        return f"{self.article} · {self.name}"

    @property
    def is_regular(self) -> bool:
        return self.months >= self.REGULAR_MONTHS

    @property
    def margin(self):
        return (self.revenue - self.cost) / self.revenue if self.revenue else None
