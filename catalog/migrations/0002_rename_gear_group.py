"""Группа «gear» по факту — в основном перчаточные ящики (правило GLOVE*), а не одежда.
Переименовываем только название; код и правила разметки те же. Название, уже исправленное
менеджером вручную, не трогаем."""

from django.db import migrations

OLD, NEW = "Экипировка и одежда", "Перчаточные ящики, шлемы, экипировка"


def forward(apps, schema_editor):
    apps.get_model("catalog", "ItemGroup").objects.filter(code="gear", name=OLD).update(name=NEW)


def backward(apps, schema_editor):
    apps.get_model("catalog", "ItemGroup").objects.filter(code="gear", name=NEW).update(name=OLD)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunPython(forward, backward)]
