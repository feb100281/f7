from django.db import models

from .department import Department


class DocKind(models.TextChoices):
    """Канал продаж — по виду документа 1С."""

    SERVICE = "service", "Наряд (сервис)"
    SALE = "sale", "Реализация"
    RETAIL = "retail", "Розница"
    RETURN = "return", "Возврат"
    CORRECTION = "correction", "Корректировка"
    OTHER = "other", "Прочее"


class SalesDoc(models.Model):
    """Документ продажи 1С (регистратор): реализация, наряд, отчёт о розничных продажах, возврат."""

    kind = models.CharField(verbose_name="Канал", max_length=12, choices=DocKind.choices, db_index=True)
    doc_type = models.CharField(verbose_name="Вид документа 1С", max_length=80)
    number = models.CharField(verbose_name="Номер", max_length=40)
    dt = models.DateTimeField(verbose_name="Дата и время")
    date = models.DateField(verbose_name="Дата", db_index=True)
    department = models.ForeignKey(
        Department,
        verbose_name="Подразделение",
        on_delete=models.PROTECT,
        related_name="docs",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Документ продажи"
        verbose_name_plural = "Документы продаж"
        ordering = ["-dt"]
        constraints = [
            models.UniqueConstraint(fields=["doc_type", "number", "dt"], name="sales_doc_unique"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.number} от {self.dt:%d.%m.%Y}"
