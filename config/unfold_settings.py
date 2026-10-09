from django.templatetags.static import static
from django.urls import reverse_lazy

UNFOLD_SETTINGS = {
    "SITE_TITLE": "FORMULA7",
    "SITE_HEADER": "FORMULA7",
    "SITE_SUBHEADER": "Запчасти · отдел продаж",
    "SITE_URL": "/",
    "SITE_SYMBOL": "sailing",
    "SITE_FAVICONS": [
        {
            "rel": "icon",
            "type": "image/svg+xml",
            "href": lambda request: static("img/favicon.svg"),
        },
    ],
    "DASHBOARD_CALLBACK": "config.dashboard.dashboard_callback",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_BACK_BUTTON": True,
    "BORDER_RADIUS": "4px",
    "COLORS": {
        # Палитра formula7.ru: фирменный красный #ED1C25 (кнопки «Перейти в каталог»)
        # как primary вместо стандартного фиолетового Unfold.
        "primary": {
            "50":  "#FEF2F2",
            "100": "#FDE3E4",
            "200": "#FBCBCD",
            "300": "#F7A3A6",
            "400": "#F16A6F",
            "500": "#ED1C25",  # F7 Red — основной
            "600": "#D3141C",
            "700": "#B01017",
            "800": "#8E1218",
            "900": "#76151A",
            "950": "#400609",
        },
    },
    "STYLES": [
        lambda request: static("css/output.css"),
    ],
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": "Главная",
                "separator": False,
                "items": [
                    {
                        "title": "Рабочий стол",
                        "icon": "space_dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                ],
            },
            {
                "title": "Номенклатура",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Товарные группы",
                        "icon": "category",
                        "link": reverse_lazy("admin:catalog_itemgroup_changelist"),
                    },
                    {
                        "title": "Номенклатура",
                        "icon": "inventory_2",
                        "link": reverse_lazy("admin:catalog_item_changelist"),
                    },
                    {
                        "title": "Техника",
                        "icon": "directions_boat",
                        "link": reverse_lazy("admin:catalog_platform_changelist"),
                    },
                ],
            },
            {
                "title": "Продажи",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Обзор продаж",
                        "icon": "monitoring",
                        "link": reverse_lazy("sales_dashboard_overview"),
                    },
                    {
                        "title": "Товарные группы",
                        "icon": "donut_large",
                        "link": reverse_lazy("sales_dashboard_groups"),
                    },
                    {
                        "title": "Сервис (наряды)",
                        "icon": "build",
                        "link": reverse_lazy("sales_dashboard_service"),
                    },
                    {
                        "title": "Салоны",
                        "icon": "location_city",
                        "link": reverse_lazy("sales_dashboard_departments"),
                    },
                    {
                        "title": "Сезонность",
                        "icon": "calendar_month",
                        "link": reverse_lazy("sales_dashboard_season"),
                    },
                    {
                        "title": "Строки продаж",
                        "icon": "list_alt",
                        "link": reverse_lazy("admin:sales_salesline_changelist"),
                    },
                    {
                        "title": "Документы",
                        "icon": "receipt_long",
                        "link": reverse_lazy("admin:sales_salesdoc_changelist"),
                    },
                    {
                        "title": "Подразделения",
                        "icon": "storefront",
                        "link": reverse_lazy("admin:sales_department_changelist"),
                    },
                ],
            },
            {
                "title": "Прогноз",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Прогноз выручки",
                        "icon": "trending_up",
                        "link": reverse_lazy("forecast_dashboard_overview"),
                    },
                    {
                        "title": "Проверка на прошлом",
                        "icon": "fact_check",
                        "link": reverse_lazy("forecast_dashboard_backtest"),
                    },
                    {
                        "title": "Подбор параметров",
                        "icon": "tune",
                        "link": reverse_lazy("admin:forecast_tunerun_changelist"),
                    },
                    {
                        "title": "Все прогнозы",
                        "icon": "history",
                        "link": reverse_lazy("admin:forecast_forecastrun_changelist"),
                    },
                ],
            },
            {
                "title": "Витрины",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Артикул × месяц",
                        "icon": "calendar_view_month",
                        "link": reverse_lazy("admin:marts_martitemmonth_changelist"),
                    },
                ],
            },
            {
                "title": "Система",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Команды",
                        "icon": "wand_shine",
                        "link": reverse_lazy("admin:core_jobs_changelist"),
                    },
                    {
                        "title": "Пользователи",
                        "icon": "person_3",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                    {
                        "title": "Группы",
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
        ],
    },
}
