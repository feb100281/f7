"""
Витрины — таблицы, которые строит DuckDB по SQL из sql/marts/ (команда «Пересчитать витрины»).

managed = False: Django эти таблицы не создаёт и не мигрирует, только читает.
DuckDB создаёт их без внешних ключей, поэтому связи объявлены с db_constraint=False
и on_delete=DO_NOTHING — в базе ограничения нет, а JOIN в ORM (item__group, department)
работает как обычно. Группа артикула в витринах не хранится: фильтр по item__group
всегда показывает текущую группу.
"""

from django.db import models

from catalog.models import Item, ItemGroup
from sales.models import Department, DocKind


def _fk(model, **kw):
    return models.ForeignKey(model, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+", **kw)


class MartItemMonth(models.Model):
    """Артикул × месяц × канал × подразделение. SQL: sql/marts/item_month.sql"""

    id = models.BigIntegerField(primary_key=True)
    item = _fk(Item, verbose_name="Артикул")
    month = models.DateField(verbose_name="Месяц")
    kind = models.CharField(verbose_name="Канал", max_length=12, choices=DocKind.choices)
    department = _fk(Department, verbose_name="Подразделение", null=True)
    qty = models.FloatField(verbose_name="Кол-во")
    revenue = models.FloatField(verbose_name="Выручка с НДС")
    cost = models.FloatField(verbose_name="Себестоимость")
    docs = models.BigIntegerField(verbose_name="Документов")
    lines = models.BigIntegerField(verbose_name="Строк")
    lines_no_revenue = models.BigIntegerField(verbose_name="Строк без выручки")

    class Meta:
        managed = False
        db_table = "mart_item_month"
        verbose_name = "Артикул × месяц"
        verbose_name_plural = "Артикул × месяц"
        ordering = ["-month", "-revenue"]


class MartItemStats(models.Model):
    """Статистика продаж по артикулу, одна строка на артикул. SQL: sql/marts/item_stats.sql"""

    item = models.OneToOneField(
        Item, primary_key=True, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="mart_stats", verbose_name="Артикул",
    )
    first_sale = models.DateField(verbose_name="Первая продажа", null=True)
    last_sale = models.DateField(verbose_name="Последняя продажа", null=True)
    qty = models.FloatField(verbose_name="Кол-во")
    revenue = models.FloatField(verbose_name="Выручка с НДС")
    cost = models.FloatField(verbose_name="Себестоимость")
    docs = models.BigIntegerField(verbose_name="Документов")
    months = models.BigIntegerField(verbose_name="Месяцев с продажами")
    months_12 = models.BigIntegerField(verbose_name="Месяцев с продажами за 12 мес.")
    qty_12 = models.FloatField(verbose_name="Кол-во за 12 мес.")
    qty_service = models.FloatField(verbose_name="Кол-во в нарядах")
    qty_sale = models.FloatField(verbose_name="Кол-во в реализации")
    qty_retail = models.FloatField(verbose_name="Кол-во в рознице")

    class Meta:
        managed = False
        db_table = "mart_item_stats"
        verbose_name = "Статистика артикула"
        verbose_name_plural = "Статистика артикулов"
        ordering = ["-revenue"]


# ---------------------------------------------------------------------------
# Витрины под дашборды раздела «Продажи»
# ---------------------------------------------------------------------------

class MartSalesMonth(models.Model):
    """Обзор продаж, салоны: месяц × канал × подразделение. SQL: sql/marts/sales_month.sql"""

    id = models.BigIntegerField(primary_key=True)
    month = models.DateField("Месяц")
    kind = models.CharField("Канал", max_length=12, choices=DocKind.choices)
    department = _fk(Department, verbose_name="Подразделение", null=True)
    revenue = models.FloatField("Выручка с НДС")
    cost = models.FloatField("Себестоимость")
    qty = models.FloatField("Кол-во")
    docs = models.BigIntegerField("Документов")
    lines = models.BigIntegerField("Строк")
    lines_no_revenue = models.BigIntegerField("Строк без выручки")
    items = models.BigIntegerField("Артикулов")

    class Meta:
        managed = False
        db_table = "mart_sales_month"
        verbose_name = verbose_name_plural = "Продажи × месяц"


class MartGroupMonth(models.Model):
    """Товарные группы: месяц × группа × канал × подразделение. SQL: sql/marts/group_month.sql"""

    id = models.BigIntegerField(primary_key=True)
    month = models.DateField("Месяц")
    group = _fk(ItemGroup, verbose_name="Товарная группа", null=True)
    kind = models.CharField("Канал", max_length=12, choices=DocKind.choices)
    department = _fk(Department, verbose_name="Подразделение", null=True)
    revenue = models.FloatField("Выручка с НДС")
    cost = models.FloatField("Себестоимость")
    qty = models.FloatField("Кол-во")
    lines = models.BigIntegerField("Строк")
    docs = models.BigIntegerField("Документов")
    items = models.BigIntegerField("Артикулов")

    class Meta:
        managed = False
        db_table = "mart_group_month"
        verbose_name = verbose_name_plural = "Группы × месяц"


class MartServiceMonth(models.Model):
    """Сервис: наряды по месяцам × подразделение. SQL: sql/marts/service_month.sql"""

    id = models.BigIntegerField(primary_key=True)
    month = models.DateField("Месяц")
    department = _fk(Department, verbose_name="Подразделение", null=True)
    orders = models.BigIntegerField("Нарядов")
    orders_consumable = models.BigIntegerField("Нарядов с расходниками")
    orders_no_revenue = models.BigIntegerField("Нарядов без выручки")
    lines = models.BigIntegerField("Строк")
    qty = models.FloatField("Кол-во")
    qty_consumable = models.FloatField("Кол-во расходников")
    revenue = models.FloatField("Выручка с НДС")
    cost = models.FloatField("Себестоимость")

    class Meta:
        managed = False
        db_table = "mart_service_month"
        verbose_name = verbose_name_plural = "Наряды × месяц"


class MartServiceItems(models.Model):
    """Сервис: артикул × месяц × подразделение в нарядах. SQL: sql/marts/service_items.sql"""

    id = models.BigIntegerField(primary_key=True)
    item = _fk(Item, verbose_name="Артикул")
    group = _fk(ItemGroup, verbose_name="Товарная группа", null=True)
    month = models.DateField("Месяц")
    department = _fk(Department, verbose_name="Подразделение", null=True)
    orders = models.BigIntegerField("Нарядов")
    qty = models.FloatField("Кол-во")
    revenue = models.FloatField("Выручка с НДС")
    cost = models.FloatField("Себестоимость")

    class Meta:
        managed = False
        db_table = "mart_service_items"
        verbose_name = verbose_name_plural = "Артикулы в нарядах"


class MartSeason(models.Model):
    """Сезонность: сезон × месяц сезона × канал × группа × подразделение. SQL: sql/marts/season.sql"""

    id = models.BigIntegerField(primary_key=True)
    season = models.BigIntegerField("Сезон (год начала)")
    season_month = models.BigIntegerField("Месяц сезона (окт = 1)")
    kind = models.CharField("Канал", max_length=12, choices=DocKind.choices)
    group = _fk(ItemGroup, verbose_name="Товарная группа", null=True)
    department = _fk(Department, verbose_name="Подразделение", null=True)
    qty = models.FloatField("Кол-во")
    revenue = models.FloatField("Выручка с НДС")
    lines = models.BigIntegerField("Строк")

    class Meta:
        managed = False
        db_table = "mart_season"
        verbose_name = verbose_name_plural = "Сезонность"


class MartMeta(models.Model):
    """Отметка о пересчёте витрин (одна строка). SQL: sql/marts/_meta.sql"""

    id = models.BigIntegerField(primary_key=True)
    built_at = models.BigIntegerField("Пересчитано (unix)")
    last_month = models.DateField("Последний месяц данных", null=True)
    last_date = models.DateField("Последняя дата данных", null=True)
    lines = models.BigIntegerField("Строк продаж")

    class Meta:
        managed = False
        db_table = "mart_meta"
        verbose_name = verbose_name_plural = "Пересчёт витрин"
