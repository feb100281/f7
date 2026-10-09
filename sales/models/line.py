from django.db import models

from catalog.models import Item

from .doc import SalesDoc


class SalesLine(models.Model):
    """
    Строка продажи: документ × артикул. Храним только факты — количество и суммы.
    Группа, тип спроса, техника берутся через артикул (item → group), поэтому
    если менеджер перенесёт артикул в другую группу, все продажи сразу «переедут» с ним.
    Возвраты — с минусом в количестве и суммах (как в 1С).
    """

    doc = models.ForeignKey(SalesDoc, verbose_name="Документ", on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, verbose_name="Артикул", on_delete=models.PROTECT, related_name="sales")
    qty = models.DecimalField(verbose_name="Кол-во", max_digits=14, decimal_places=3)
    revenue = models.DecimalField(
        verbose_name="Выручка с НДС", max_digits=16, decimal_places=2, null=True, blank=True,
        help_text="Пусто — строка без выручки (например, гарантийный наряд)",
    )
    cost = models.DecimalField(verbose_name="Себестоимость", max_digits=16, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Строка продажи"
        verbose_name_plural = "Строки продаж"
        ordering = ["-doc__dt", "id"]
        indexes = [
            models.Index(fields=["item", "doc"]),
        ]

    def __str__(self):
        return f"{self.item.article} × {self.qty}"

    @property
    def margin(self):
        if self.revenue is None or self.cost is None:
            return None
        return self.revenue - self.cost
