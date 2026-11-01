"""
Остатки товара — срезы на дату. Каждая загрузка файла из 1С («Артикул / Номенклатура / Доступно /
Поступит») — отдельный срез: старые не затираются, по ним видно, как менялся склад.

    StockSnapshot — срез на дату (один на дату: повторная загрузка заменяет строки) + сводка
    StockLine     — строка среза: артикул, доступно, поступит (в пути)

Остаток — по всей компании (закупка централизованная). В расчёте заказа остатки старых номеров
складываются на актуальный (семейства замен), как и прогноз.
"""

from __future__ import annotations

from django.db import models


class StockSnapshot(models.Model):
    date = models.DateField("Остатки на дату", unique=True)
    file = models.FileField("Файл", upload_to="stock/", blank=True)
    filename = models.CharField("Имя файла", max_length=255, blank=True)
    uploaded = models.DateTimeField("Загружен", auto_now_add=True)
    # именем, не ссылкой: пользователи на сервере свои, публикация переносит срезы без них
    uploaded_by = models.CharField("Кто загрузил", max_length=150, blank=True)
    note = models.CharField("Комментарий", max_length=255, blank=True)

    # --- сводка (считается при загрузке)
    lines_n = models.PositiveIntegerField("Строк", default=0)
    matched_n = models.PositiveIntegerField("Есть в номенклатуре", default=0,
                                            help_text="Артикул найден среди проданных за 5 лет")
    available = models.FloatField("Доступно, шт.", default=0)
    incoming = models.FloatField("Поступит, шт.", default=0)
    value = models.FloatField("Доступно по с/с, ₽", default=0,
                              help_text="По последней себестоимости продажи; у никогда не продававшихся с/с нет")
    value_known_n = models.PositiveIntegerField("Строк с известной с/с", default=0)
    dead_n = models.PositiveIntegerField("Без продаж больше года, арт.", default=0,
                                         help_text="Есть на складе, но не продавались 12 мес. или не продавались никогда")
    dead_qty = models.FloatField("Без продаж больше года, шт.", default=0)
    dead_value = models.FloatField("Без продаж больше года по с/с, ₽", default=0)
    negative_n = models.PositiveIntegerField("Отрицательный остаток, арт.", default=0)

    # --- к заказу при параметрах по умолчанию (для рабочего стола); пересчитывается, когда появится
    # новый прогноз. На «Штуках» заказ считается вживую по выбранным параметрам.
    order_run_id = models.IntegerField("По прогнозу №", null=True, blank=True)
    order_params = models.JSONField("Параметры заказа", default=dict, blank=True)
    order_n = models.PositiveIntegerField("К заказу, арт.", default=0)
    order_qty = models.FloatField("К заказу, шт.", default=0)
    order_cost = models.FloatField("К заказу по с/с, ₽", default=0)

    class Meta:
        verbose_name = "Остатки на дату"
        verbose_name_plural = "Остатки на дату"
        ordering = ["-date"]

    def __str__(self):
        return f"Остатки на {self.date:%d.%m.%Y}"


class StockLine(models.Model):
    snapshot = models.ForeignKey(StockSnapshot, verbose_name="Срез", on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey("catalog.Item", verbose_name="Номенклатура", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="stock_lines")
    article = models.CharField("Артикул", max_length=40)
    name = models.CharField("Название в 1С", max_length=255, blank=True)
    available = models.FloatField("Доступно, шт.", default=0)
    incoming = models.FloatField("Поступит, шт.", default=0)
    cost = models.FloatField("С/с последняя, ₽/шт.", null=True, blank=True)
    last_sale = models.DateField("Последняя продажа", null=True, blank=True)

    class Meta:
        verbose_name = "Строка остатков"
        verbose_name_plural = "Строки остатков"
        ordering = ["snapshot", "article"]
        constraints = [models.UniqueConstraint(fields=["snapshot", "article"], name="stock_line_snapshot_article")]
        indexes = [models.Index(fields=["article"]), models.Index(fields=["item", "snapshot"])]

    def __str__(self):
        return f"{self.article} · {self.snapshot.date:%d.%m.%Y}"
