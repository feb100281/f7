"""
Составные ячейки для @display-полей.

FirstCol — «визитка» записи в первой колонке списка: аватар, название
и подпись. Разметка держится на классах .f7-field-* из input.css.
"""

from __future__ import annotations

from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

EMPTY = mark_safe('<span class="f7-field-sub">—</span>')


def hint(value) -> str:
    """Полный текст в title — ячейки обрезаются по ширине колонки."""

    if value in (None, "") or isinstance(value, SafeString):
        return ""

    return str(value)


class FirstCol:
    """
        FirstCol(name, subtitle_html, avatar_url).avatar_name_subtext
    """

    def __init__(
        self,
        name=None,
        subtext=None,
        avatar: str | None = None,
        note=None,
    ) -> None:
        self.name = name
        self.subtext = subtext
        self.avatar = avatar
        self.note = note

    # ------------------------------------------------------------------
    # Кусочки
    # ------------------------------------------------------------------

    @property
    def avatar_html(self) -> SafeString:
        if not self.avatar:
            return mark_safe("")

        return format_html(
            '<img src="{}" class="f7-field-avatar-img" loading="lazy" alt="">',
            self.avatar,
        )

    @property
    def name_html(self) -> SafeString:
        return format_html(
            '<span class="f7-field-name" title="{}">{}</span>',
            hint(self.name),
            self.name or "—",
        )

    @property
    def subtext_html(self) -> SafeString:
        if self.subtext in (None, ""):
            return mark_safe("")

        return format_html(
            '<span class="f7-field-sub">{}</span>',
            self.subtext,
        )

    # ------------------------------------------------------------------
    # Готовые варианты
    # ------------------------------------------------------------------

    @property
    def avatar_name_subtext(self) -> SafeString:
        return format_html(
            '<div class="f7-field-row">{}'
            '<span class="f7-field-stack">{}{}</span>'
            "</div>",
            self.avatar_html,
            self.name_html,
            self.subtext_html,
        )

    # Синоним (совместимость с проектом cr)
    avatar_name_subtex = avatar_name_subtext

    @property
    def name_subtext(self) -> SafeString:
        return format_html(
            '<div class="f7-field-row">'
            '<span class="f7-field-stack">{}{}</span>'
            "</div>",
            self.name_html,
            self.subtext_html,
        )

    @property
    def simple(self) -> SafeString:
        if self.name in (None, ""):
            return EMPTY

        return format_html(
            '<span class="f7-field-simple">{}</span>',
            self.name,
        )

    @property
    def title_sub(self) -> SafeString:
        return format_html(
            '<div class="f7-field-title-wrap">'
            '<div class="f7-field-title">{}'
            '<span class="f7-field-title-note">{}</span>'
            "</div>"
            '<div class="f7-field-title-sub">{}</div>'
            "</div>",
            self.name or "—",
            self.note or "",
            self.subtext or "",
        )


class Stack:
    """Несколько строк в одной ячейке: первая — основная, остальные — подписи."""

    def __init__(self, *rows) -> None:
        self.rows = [row for row in rows if row not in (None, "")]

    @property
    def html(self) -> SafeString:
        if not self.rows:
            return EMPTY

        head, *rest = self.rows

        body = format_html(
            '<span class="f7-field-name" title="{}">{}</span>',
            hint(head),
            head,
        )

        for row in rest:
            body += format_html(
                '<span class="f7-field-sub" title="{}">{}</span>',
                hint(row),
                row,
            )

        return format_html(
            '<span class="f7-field-stack">{}</span>',
            body,
        )

    def __str__(self) -> str:
        return self.html
