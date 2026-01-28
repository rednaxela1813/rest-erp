from django.urls import path

from apps.ops_dashboard.views import (
    ops_dashboard_metrics_view,
    ops_dashboard_select_org_view,
    ops_dashboard_view,
)

urlpatterns = [
    path("dashboard/", ops_dashboard_view, name="ops-dashboard"),
    path("dashboard/metrics/", ops_dashboard_metrics_view, name="ops-dashboard-metrics"),
    path("dashboard/select-org/", ops_dashboard_select_org_view, name="ops-dashboard-select-org"),
]
