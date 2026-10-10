"""
Номенклатура. Менеджер меняет группу тремя способами:
    • в списке — колонка «Группа» редактируется прямо в строке (list_editable);
    • массово — отметить артикулы → действие «Назначить группу» + выбрать группу рядом;
    • в карточке артикула.
Любая ручная смена группы или техники помечает артикул как «Вручную» — импорт продаж
и пересчёт по правилам такой артикул больше не трогают. Вернуть автоматику —
действие «Вернуть группу по правилам».
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeNumericFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action, display
from unfold.forms import ActionForm
from unfold.widgets import UnfoldAdminSelectWidget

from catalog.models import DemandType, GroupSource, Item, ItemGroup, ItemReplacement, ReplacementSource
from catalog.services.classify import reclassify
from core.admins import AppModelAdmin, AppTabularInline, FirstCol

from .common import demand_badge, money, num_cell, qty, source_badge


# --------------------------------------------------------------------------
# Форма действий: рядом с выпадашкой действий — выбор группы для массового назначения
# --------------------------------------------------------------------------
class ItemActionForm(ActionForm):
    target_group = forms.ModelChoiceField(
        queryset=ItemGroup.objects.all(),
        required=False,
        label="",
        empty_label="— группа для «Назначить группу» —",
        widget=UnfoldAdminSelectWidget(attrs={
            "class": " ".join([
                "group-[.changelist-actions]:appearance-none",
                "group-[.changelist-actions]:!bg-white/20",
                "group-[.changelist-actions]:font-medium",
                "group-[.changelist-actions]:px-2",
                "group-[.changelist-actions]:py-1",
                "group-[.changelist-actions]:pr-8",
                "group-[.changelist-actions]:rounded-default",
                "group-[.changelist-actions]:!text-current",
                "group-[.changelist-actions]:*:text-base-700",
                "group-[.changelist-actions]:lg:w-72",
            ]),
            "aria-label": "Группа",
        }),
    )


# --------------------------------------------------------------------------
# Форма строки списка: только выбор группы, без кнопок «добавить/изменить» рядом
# --------------------------------------------------------------------------
class ItemChangelistForm(forms.ModelForm):
    group = forms.ModelChoiceField(
        queryset=ItemGroup.objects.all(),
        required=False,
        label="Группа",
        widget=UnfoldAdminSelectWidget(attrs={"class": "f7-group-select"}),
    )

    class Meta:
        model = Item
        fields = ["group"]


# --------------------------------------------------------------------------
# Фильтры
# --------------------------------------------------------------------------
class RegularityFilter(admin.SimpleListFilter):
    title = "Регулярность продаж"
    parameter_name = "regularity"

    def lookups(self, request, model_admin):
        return [
            ("regular", f"Регулярные ({Item.REGULAR_MONTHS}+ мес.)"),
            ("often", "Частые (6–23 мес.)"),
            ("rare", "Редкие (2–5 мес.)"),
            ("once", "Разовые (1 мес.)"),
        ]

    def queryset(self, request, queryset):
        return {
            "regular": queryset.filter(months__gte=Item.REGULAR_MONTHS),
            "often": queryset.filter(months__gte=6, months__lt=Item.REGULAR_MONTHS),
            "rare": queryset.filter(months__gte=2, months__lt=6),
            "once": queryset.filter(months__lte=1),
        }.get(self.value(), queryset)


class DemandTypeFilter(admin.SimpleListFilter):
    title = "Тип спроса"
    parameter_name = "demand"

    def lookups(self, request, model_admin):
        return DemandType.choices

    def queryset(self, request, queryset):
        return queryset.filter(group__demand_type=self.value()) if self.value() else queryset


class FamilyFilter(admin.SimpleListFilter):
    title = "Замены номеров"
    parameter_name = "family"

    def lookups(self, request, model_admin):
        return [
            ("head", "Актуальный номер семьи"),
            ("member", "Старый номер (переведён)"),
            ("any", "Есть замены"),
            ("none", "Без замен"),
        ]

    def queryset(self, request, queryset):
        heads = Item.objects.filter(family_members__isnull=False).values("pk")
        return {
            "head": queryset.filter(pk__in=heads),
            "member": queryset.exclude(family_head=None),
            "any": queryset.filter(Q(pk__in=heads) | Q(family_head__isnull=False)),
            "none": queryset.filter(family_head=None).exclude(pk__in=heads),
        }.get(self.value(), queryset)


# --------------------------------------------------------------------------
# Замены в карточке артикула
# --------------------------------------------------------------------------
class _ReplacementInline(AppTabularInline):
    model = ItemReplacement
    autocomplete_fields = ["old", "new"]
    fields = ["old", "new", "status", "source", "note"]
    readonly_fields = ["source"]
    show_change_link = False


class ReplacedByInline(_ReplacementInline):
    fk_name = "old"
    fields = ["new", "status", "source", "note"]
    verbose_name = "замена на новый номер"
    verbose_name_plural = "Заменён на"


class ReplacesInline(_ReplacementInline):
    fk_name = "new"
    fields = ["old", "status", "source", "note"]
    verbose_name = "старый номер"
    verbose_name_plural = "Заменяет"


# --------------------------------------------------------------------------
@admin.register(Item)
class ItemAdmin(AppModelAdmin):
    action_form = ItemActionForm
    list_per_page = 100

    list_display = ["item_col", "group", "platform_col", "revenue_col", "months_col", "last_sale_col", "source_col"]
    list_display_links = ["item_col"]
    list_editable = ["group"]
    list_select_related = ["group", "platform", "family_head"]
    inlines = [ReplacesInline, ReplacedByInline]
    list_filter = [
        ("group", RelatedDropdownFilter),
        DemandTypeFilter,
        ("platform", RelatedDropdownFilter),
        ("group_source", ChoicesDropdownFilter),
        RegularityFilter,
        FamilyFilter,
        "is_new",
        ("revenue", RangeNumericFilter),
    ]
    search_fields = ["article", "name", "name_1c"]
    ordering = ["-revenue"]

    readonly_fields = [
        "name_1c", "group_source", "group_rule",
        "first_sale", "last_sale", "qty", "revenue", "cost", "docs", "months", "created", "updated",
        "family_col", "is_new", "new_since",
    ]
    fieldsets = (
        ("Артикул", {"fields": [("article", "name"), "name_1c", "note", "family_col"]}),
        ("Группа", {"fields": [("group", "platform"), ("group_source", "group_rule")]}),
        ("Продажи", {
            "classes": ["tab"],
            "fields": [("first_sale", "last_sale"), ("is_new", "new_since"), ("qty", "docs", "months"), ("revenue", "cost"), ("created", "updated")],
        }),
    )

    actions = ["assign_group", "reset_to_rules"]

    def get_changelist_form(self, request, **kwargs):
        return ItemChangelistForm

    # --- колонки
    @display(description="Техника", ordering="platform__sort")
    def platform_col(self, obj):
        return obj.platform.name if obj.platform else "—"

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_members=Count("family_members", distinct=True))

    @display(description="Артикул", ordering="article")
    def item_col(self, obj):
        cell = FirstCol(obj.name, obj.article).name_subtext
        if obj.family_head_id:
            tag = format_html('<span class="f7-family" title="Старый номер: прогноз и статистика идут на {}">'
                              '<span class="material-symbols-outlined">arrow_forward</span>{}</span>',
                              obj.family_head.article, obj.family_head.article)
        elif getattr(obj, "n_members", 0):
            n = obj.n_members
            tag = format_html('<span class="f7-family" title="Актуальный номер: в прогнозе вместе со старыми">'
                              '<span class="material-symbols-outlined">merge</span>заменяет {} {}</span>',
                              n, "номер" if n == 1 else "номера" if n < 5 else "номеров")
        else:
            tag = ""
        if obj.is_new:
            tag = format_html('{}<span class="f7-new" title="Продажи пошли {}: короткая история, прогноз проверять вручную">'
                              'новинка с {}</span>', tag, f"{obj.new_since:%d.%m.%Y}", f"{obj.new_since:%m.%Y}")
        if not tag:
            return cell
        return format_html('<span class="f7-field-stack">{}{}</span>', cell, tag)

    @display(description="Семейство")
    def family_col(self, obj):
        if not obj or not obj.pk:
            return "—"
        link = lambda i: format_html('<a class="f7-link" href="{}">{}</a>',  # noqa: E731
                                     reverse("admin:catalog_item_change", args=[i.pk]), i.article)
        if obj.family_head_id:
            return format_html("Старый номер — прогноз и статистика идут на актуальный {}", link(obj.family_head))
        members = list(obj.family_members.order_by("article"))
        if members:
            return format_html("Актуальный номер, вместе с ним считаются: {}",
                               format_html_join(", ", "{}", ((link(m),) for m in members)))
        return "Самостоятельный номер (замен нет)"

    @display(description="Тип спроса", ordering="group__demand_type")
    def demand_col(self, obj):
        return demand_badge(obj.group.demand_type if obj.group else None)

    @display(description="Выручка, ₽", ordering="revenue")
    def revenue_col(self, obj):
        return num_cell(money(obj.revenue), f"{qty(obj.qty)} шт.")

    @display(description="Месяцев", ordering="months")
    def months_col(self, obj):
        return num_cell(str(obj.months), "регулярный" if obj.is_regular else None)

    @display(description="Посл. продажа", ordering="last_sale")
    def last_sale_col(self, obj):
        return obj.last_sale.strftime("%d.%m.%Y") if obj.last_sale else "—"

    @display(description="Источник", ordering="group_source")
    def source_col(self, obj):
        return source_badge(obj)

    # --- замены из карточки: новые пары — «Вручную», семейства пересобираются сразу
    def save_formset(self, request, form, formset, change):
        if formset.model is ItemReplacement:
            for f in formset.forms:
                if f.instance and not f.instance.pk and f.has_changed():
                    f.instance.source = ReplacementSource.MANUAL
        super().save_formset(request, form, formset, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        from catalog.services.replacements import rebuild_families
        rebuild_families(log=lambda *_: None)

    # --- ручная правка = ручная разметка
    def save_model(self, request, obj, form, change):
        if change and form is not None and {"group", "platform"} & set(form.changed_data):
            obj.group_source = GroupSource.MANUAL
            obj.group_rule = request.user.get_username()[:120]
        super().save_model(request, obj, form, change)

    # --- действия
    @action(description="Назначить группу (выбрать справа)")
    def assign_group(self, request, queryset):
        group_id = request.POST.get("target_group")
        group = ItemGroup.objects.filter(pk=group_id).first() if group_id else None
        if not group:
            messages.warning(request, "Выберите группу в списке рядом с действием")
            return
        n = queryset.update(
            group=group, group_source=GroupSource.MANUAL,
            group_rule=request.user.get_username()[:120], updated=timezone.now(),
        )
        messages.success(request, f"Группа «{group}» назначена: {n} арт. (помечены как ручная разметка)")

    @action(description="Вернуть группу по правилам")
    def reset_to_rules(self, request, queryset):
        r = reclassify(queryset, include_manual=True)
        messages.success(request, f"Пересчитано по правилам: {r['checked']} арт., изменилось: {r['changed']}")
