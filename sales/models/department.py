from django.db import models


class Department(models.Model):
    """
    Подразделение (салон) — по префиксу номера документа 1С: 78УТ-004063 → «78УТ».
    Создаётся при импорте автоматически, название заполняют в админке.
    """

    prefix = models.CharField(verbose_name="Префикс", max_length=20, unique=True)
    name = models.CharField(verbose_name="Салон", max_length=120, blank=True)
    city = models.CharField(verbose_name="Город", max_length=60, blank=True)
    is_active = models.BooleanField(verbose_name="Работает", default=True)
    note = models.TextField(verbose_name="Комментарий", blank=True)

    class Meta:
        verbose_name = "Подразделение"
        verbose_name_plural = "Подразделения"
        ordering = ["prefix"]

    def __str__(self):
        return f"{self.prefix} · {self.name}" if self.name else self.prefix
