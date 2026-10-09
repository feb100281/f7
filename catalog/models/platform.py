from django.db import models


class Platform(models.Model):
    """Техника, к которой относится запчасть: SSV/ATV, снегоходы, гидроциклы, двигатели Rotax."""

    code = models.SlugField(verbose_name="Код", max_length=20, unique=True)
    name = models.CharField(verbose_name="Техника", max_length=80)
    sort = models.PositiveSmallIntegerField(verbose_name="Порядок", default=100)

    class Meta:
        verbose_name = "Техника"
        verbose_name_plural = "Техника"
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name
