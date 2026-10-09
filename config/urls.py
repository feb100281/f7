from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from forecast import views as fc
from sales.dashboards import views as dash

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    # дашборды «Продажи» — до admin.site.urls, чтобы админка не перехватила адрес
    path("admin/sales/dashboard/", RedirectView.as_view(pattern_name="sales_dashboard_overview", permanent=False)),
    path("admin/sales/dashboard/overview/", dash.overview, name="sales_dashboard_overview"),
    path("admin/sales/dashboard/groups/", dash.groups, name="sales_dashboard_groups"),
    path("admin/sales/dashboard/service/", dash.service, name="sales_dashboard_service"),
    path("admin/sales/dashboard/departments/", dash.departments, name="sales_dashboard_departments"),
    path("admin/sales/dashboard/season/", dash.season, name="sales_dashboard_season"),
    path("admin/forecast/dashboard/", fc.overview, name="forecast_dashboard_overview"),
    path("admin/forecast/dashboard/backtest/", fc.backtest, name="forecast_dashboard_backtest"),
    path("admin/", admin.site.urls),
]


if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
