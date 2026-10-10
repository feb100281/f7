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
    families = models.BooleanField("Штуки по семействам номеров", default=False,
                                   help_text="Старые номера посчитаны вместе с актуальным (замены номеров)")

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


# ---------------------------------------------------------------------------
# Лестница: прогноз выручки → группы → артикулы → штуки (sql/forecast/ladder.sql)
# ---------------------------------------------------------------------------

class PriceSource(models.TextChoices):
    M6 = "6m", "медиана за 6 мес."
    M12 = "12m", "медиана за 12 мес."
    LAST = "last", "последняя продажа"
    GROUP = "group", "медиана группы"
    NONE = "none", "нет цены"


class ForecastGroup(models.Model):
    """Прогноз выручки ряда, разложенный по товарным группам, и сумма штук по её артикулам."""

    run = models.ForeignKey(ForecastRun, on_delete=models.CASCADE, related_name="groups")
    series = models.CharField("Ряд", max_length=20, choices=Series.choices)
    group = models.ForeignKey("catalog.ItemGroup", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="+", verbose_name="Товарная группа")
    month = models.DateField("Месяц")
    share = models.FloatField("Доля группы в ряду")
    revenue = models.FloatField("Прогноз выручки")
    qty = models.FloatField("Прогноз, шт.", default=0)

    class Meta:
        verbose_name = "Прогноз по группе"
        verbose_name_plural = "Прогноз по группам"
        ordering = ["run", "series", "month", "-revenue"]
        indexes = [models.Index(fields=["run", "group"])]


class ForecastItem(models.Model):
    """Прогноз штук артикула на месяц по ряду. Для месяца, в котором кончается факт, — только остаток."""

    run = models.ForeignKey(ForecastRun, on_delete=models.CASCADE, related_name="items")
    series = models.CharField("Ряд", max_length=20, choices=Series.choices)
    item = models.ForeignKey("catalog.Item", on_delete=models.CASCADE, related_name="+", verbose_name="Артикул")
    group = models.ForeignKey("catalog.ItemGroup", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="+", verbose_name="Товарная группа")
    month = models.DateField("Месяц")
    qty = models.FloatField("Прогноз, шт.")
    revenue = models.FloatField("Прогноз выручки")
    price = models.FloatField("Цена", null=True)
    price_source = models.CharField("Откуда цена", max_length=10, choices=PriceSource.choices)

    class Meta:
        verbose_name = "Прогноз по артикулу"
        verbose_name_plural = "Прогноз по артикулам"
        ordering = ["run", "series", "month", "-qty"]
        indexes = [models.Index(fields=["run", "item"]), models.Index(fields=["run", "group"])]


class ItemDemandStats(models.Model):
    """Статистика спроса артикула по всей компании (витрина mart_fc_item_stats, пишет ladder.sql).
    Спрос — штуки по 12 полным месяцам, нулевые месяцы входят в среднее и разброс;
    у новинки — только месяцы с начала продаж (months_active)."""

    item = models.OneToOneField("catalog.Item", primary_key=True, db_column="item_id", db_constraint=False,
                                on_delete=models.DO_NOTHING, related_name="+", verbose_name="Артикул")
    qty12 = models.FloatField("Продано за 12 мес., шт.")
    months12 = models.IntegerField("Месяцев с продажами из 12")
    months_active = models.IntegerField("Месяцев в расчёте", default=12,
                                        help_text="12, у новинки — с месяца, когда пошли продажи")
    mean12 = models.FloatField("Среднее в месяц")
    std12 = models.FloatField("Std в месяц")
    cv12 = models.FloatField("CV", null=True)
    qty24 = models.FloatField("Продано за 24 мес., шт.")
    months24 = models.IntegerField("Месяцев с продажами из 24")
    first_sale = models.DateField("Первая продажа", null=True)
    last_sale = models.DateField("Последняя продажа", null=True)
    last_cost = models.FloatField("Себестоимость последняя, ₽/шт.", null=True)
    last_cost_date = models.DateField("Дата себестоимости", null=True)

    class Meta:
        managed = False
        db_table = "mart_fc_item_stats"
        verbose_name = "Статистика спроса"
        verbose_name_plural = "Статистика спроса"


class QtyCheckVariant(models.TextChoices):
    ITEMS = "items", "Как сейчас — каждый номер отдельно"
    FAMILIES = "families", "Со склейкой номеров"


class QtyCheck(models.Model):
    """Проверка штук на прошлом: прогноз выручки с прошлых отсечек → лестница → штуки против факта."""

    created = models.DateTimeField("Когда", auto_now_add=True)
    data_end = models.DateField("Факт по")
    months = models.PositiveSmallIntegerField("Месяцев вперёд", default=6)
    tune_runs = models.JSONField("Подборы (прогноз выручки)", default=dict)
    seconds = models.FloatField("Время, c", default=0)

    class Meta:
        verbose_name = "Проверка штук"
        verbose_name_plural = "Проверки штук"
        ordering = ["-created"]

    def __str__(self):
        return f"Проверка штук · {self.created:%d.%m.%Y %H:%M}"


class QtyCheckPoint(models.Model):
    """Одна отсечка × вариант. Ошибка = Σ|прогноз − факт| по артикулам / Σ факт (за months мес.).
    fam_* — то же только по артикулам, у которых есть замены номеров."""

    run = models.ForeignKey(QtyCheck, on_delete=models.CASCADE, related_name="points")
    cutoff = models.DateField("Отсечка")
    variant = models.CharField("Вариант", max_length=10, choices=QtyCheckVariant.choices)
    items = models.PositiveIntegerField("Артикулов", default=0)
    actual = models.FloatField("Факт, шт.")
    forecast = models.FloatField("Прогноз, шт.")
    abs_err = models.FloatField("Σ |ошибка|, шт.")
    fam_actual = models.FloatField("Факт по семействам, шт.", default=0)
    fam_forecast = models.FloatField("Прогноз по семействам, шт.", default=0)
    fam_abs_err = models.FloatField("Σ |ошибка| по семействам, шт.", default=0)

    class Meta:
        verbose_name = "Отсечка проверки штук"
        verbose_name_plural = "Отсечки проверки штук"
        ordering = ["run", "cutoff", "variant"]
