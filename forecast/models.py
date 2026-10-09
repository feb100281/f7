"""
Прогноз выручки (Prophet) по двум рядам: сервис (наряды) и реализация + розница.

    TuneRun / TuneResult / BacktestPoint — подбор параметров на прошлом (rolling-бэктест):
        каждая комбинация параметров обучается на данных до отсечки и прогнозирует N месяцев
        вперёд, прогноз сравнивается с фактом. Лучшая комбинация → BacktestPoint (с коридором).
    ForecastRun / ForecastPoint — сам прогноз вперёд. Каждый прогноз сохраняется со своей
        датой данных — когда придёт новый факт, видно, насколько он попал.
"""

from __future__ import annotations

from django.db import models


class Series(models.TextChoices):
    SERVICE = "service", "Сервис (наряды)"
    SHOP = "shop", "Реализация и розница"
    TOTAL = "total", "Всего"


# ряды, по которым строятся модели; «Всего» — сумма их прогнозов
MODEL_SERIES = [Series.SERVICE, Series.SHOP]

# какие виды документов входят в ряд (возвраты и корректировки не входят)
SERIES_KINDS = {
    Series.SERVICE: ["service"],
    Series.SHOP: ["sale", "retail"],
    Series.TOTAL: ["service", "sale", "retail"],
}


class TuneRun(models.Model):
    series = models.CharField("Ряд", max_length=20, choices=Series.choices)
    created = models.DateTimeField("Когда", auto_now_add=True)
    data_end = models.DateField("Факт по")
    horizon = models.PositiveSmallIntegerField("Горизонт, мес.")
    cutoffs = models.JSONField("Отсечки", default=list)
    combos = models.PositiveIntegerField("Комбинаций", default=0)
    seconds = models.FloatField("Время, c", default=0)

    best = models.JSONField("Лучшие параметры", default=dict)
    wape3 = models.FloatField("Ошибка 1–3 мес.", null=True)
    wape6 = models.FloatField("Ошибка на горизонте", null=True)
    bias = models.FloatField("Смещение", null=True)
    default_wape3 = models.FloatField("По умолчанию 1–3 мес.", null=True)
    default_wape6 = models.FloatField("По умолчанию на горизонте", null=True)

    class Meta:
        verbose_name = "Подбор параметров"
        verbose_name_plural = "Подбор параметров"
        ordering = ["-created"]

    def __str__(self):
        return f"{self.get_series_display()} · {self.created:%d.%m.%Y %H:%M}"


class TuneResult(models.Model):
    run = models.ForeignKey(TuneRun, on_delete=models.CASCADE, related_name="results")
    rank = models.PositiveIntegerField("Место")
    params = models.JSONField("Параметры")
    wape3 = models.FloatField("Ошибка 1–3 мес.")
    wape6 = models.FloatField("Ошибка на горизонте")
    bias = models.FloatField("Смещение")
    score = models.FloatField("Оценка")
    folds = models.JSONField("По отсечкам", default=list)
    is_default = models.BooleanField("Prophet по умолчанию", default=False)

    class Meta:
        verbose_name = "Результат подбора"
        verbose_name_plural = "Результаты подбора"
        ordering = ["run", "rank"]


class BacktestPoint(models.Model):
    """Прогноз лучшей модели с отсечки `cutoff` на месяц `month` (h — какой месяц вперёд) и факт."""

    run = models.ForeignKey(TuneRun, on_delete=models.CASCADE, related_name="points")
    cutoff = models.DateField("Отсечка")
    month = models.DateField("Месяц")
    h = models.PositiveSmallIntegerField("Месяц вперёд")
    actual = models.FloatField("Факт")
    yhat = models.FloatField("Прогноз")
    lower = models.FloatField("Нижняя граница")
    upper = models.FloatField("Верхняя граница")

    class Meta:
        verbose_name = "Точка бэктеста"
        verbose_name_plural = "Бэктест"
        ordering = ["run", "cutoff", "month"]


class ForecastRun(models.Model):
    created = models.DateTimeField("Когда", auto_now_add=True)
    data_end = models.DateField("Факт по")
    horizon = models.PositiveSmallIntegerField("Горизонт, мес.")
    params = models.JSONField("Параметры по рядам", default=dict)
    tune_runs = models.JSONField("Подбор, из которого параметры", default=dict)
    seconds = models.FloatField("Время, c", default=0)
    note = models.CharField("Комментарий", max_length=250, blank=True)

    class Meta:
        verbose_name = "Прогноз"
        verbose_name_plural = "Прогнозы"
        ordering = ["-created"]

    def __str__(self):
        return f"Прогноз по данным на {self.data_end:%d.%m.%Y}"


class ForecastPoint(models.Model):
    """Прогноз выручки на месяц. Для месяца, в котором кончается факт, yhat — только остаток
    месяца, а факт до даты данных — в actual_before (ожидание по месяцу = сумма)."""

    run = models.ForeignKey(ForecastRun, on_delete=models.CASCADE, related_name="points")
    series = models.CharField("Ряд", max_length=20, choices=Series.choices)
    month = models.DateField("Месяц")
    yhat = models.FloatField("Прогноз")
    lower = models.FloatField("Нижняя граница")
    upper = models.FloatField("Верхняя граница")
    actual_before = models.FloatField("Факт до даты прогноза", default=0)

    class Meta:
        verbose_name = "Точка прогноза"
        verbose_name_plural = "Точки прогноза"
        ordering = ["run", "series", "month"]
        constraints = [models.UniqueConstraint(fields=["run", "series", "month"], name="forecast_point_uniq")]

    @property
    def expected(self) -> float:
        return self.actual_before + self.yhat
