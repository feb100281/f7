"""
Пользователи и группы (роли) в оформлении Unfold.

Права в группе — таблица с галочками: строка — раздел админки, колонки — просмотр /
добавление / изменение / удаление. Показываются только разделы, которые есть в админке
(служебные таблицы Django и витрины скрыты). Сверху — быстрые наборы прав.
"""

from __future__ import annotations

from django import forms
from django.apps import apps
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission, User
from django.db.models import Count
from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.widgets import UnfoldAdminCheckboxSelectMultipleWidget

from core.admins import FirstCol

APPS = ["catalog", "sales", "forecast", "core", "auth"]   # порядок разделов в таблице
ACTIONS = [("view", "Просмотр"), ("add", "Добавление"), ("change", "Изменение"), ("delete", "Удаление")]


def _visible_permissions():
    """Права только на модели, у которых есть админка, в разделах из APPS."""
    registered = {(m._meta.app_label, m._meta.model_name) for m in admin.site._registry}
    qs = Permission.objects.select_related("content_type").filter(content_type__app_label__in=APPS)
    return [p for p in qs if (p.content_type.app_label, p.content_type.model) in registered]


class PermissionMatrix(forms.CheckboxSelectMultiple):
    template_name = "core/widgets/permission_matrix.html"

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        selected = {str(v) for v in (value or [])}
        rows: dict = {}
        for p in _visible_permissions():
            ct = p.content_type
            model = ct.model_class()
            key = (APPS.index(ct.app_label), ct.app_label, ct.model)
            row = rows.setdefault(key, {
                "app": apps.get_app_config(ct.app_label).verbose_name,
                "model": model._meta.verbose_name_plural if model else ct.model,
                "cells": {a: None for a, _ in ACTIONS}, "extra": [],
            })
            action = p.codename.split("_", 1)[0]
            item = {"id": str(p.pk), "checked": str(p.pk) in selected, "name": p.name}
            if p.codename == f"{action}_{ct.model}" and action in row["cells"]:
                row["cells"][action] = item
            else:
                row["extra"].append(item)
        ordered = [rows[k] for k in sorted(rows)]
        for r in ordered:
            r["cells"] = [r["cells"][a] for a, _ in ACTIONS]
        ctx["widget"].update({"rows": ordered, "actions": ACTIONS, "has_extra": any(r["extra"] for r in ordered)})
        return ctx

    def value_from_datadict(self, data, files, name):
        return data.getlist(name)


class GroupForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(), required=False, widget=PermissionMatrix, label="Права",
    )

    class Meta:
        model = Group
        fields = ["name", "permissions"]

    def clean_permissions(self):
        # права, которых нет в таблице (служебные), сохраняем как были
        chosen = set(self.cleaned_data["permissions"])
        if self.instance.pk:
            visible = {p.pk for p in _visible_permissions()}
            chosen |= {p for p in self.instance.permissions.all() if p.pk not in visible}
        return list(chosen)


admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    form = GroupForm
    list_display = ["name", "users_col", "perms_col"]
    filter_horizontal = ()

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(users_n=Count("user", distinct=True),
                                                      perms_n=Count("permissions", distinct=True))

    @display(description="Пользователей", ordering="users_n")
    def users_col(self, obj):
        return obj.users_n

    @display(description="Прав", ordering="perms_n")
    def perms_col(self, obj):
        return obj.perms_n


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    filter_horizontal = ()
    list_display = ["user_col", "email", "groups_col", "is_active", "is_staff", "last_login"]
    list_filter = ["is_active", "is_staff", "groups"]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Сотрудник", {"fields": (("first_name", "last_name"), "email")}),
        ("Доступ", {
            "fields": ("is_active", "is_staff", "is_superuser", "groups"),
            "description": "Права выдаются через группы (роли). «Персонал» — может входить в админку, "
                           "«суперпользователь» — видит и может всё.",
        }),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = ["last_login", "date_joined"]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "groups":
            kwargs["widget"] = UnfoldAdminCheckboxSelectMultipleWidget
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    @display(description="Пользователь", ordering="username")
    def user_col(self, obj):
        return FirstCol(obj.get_full_name() or obj.username, obj.username).name_subtext

    @display(description="Группы")
    def groups_col(self, obj):
        return ", ".join(g.name for g in obj.groups.all()) or "—"
