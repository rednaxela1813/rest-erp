from django.urls import path

from apps.logs_dashboard.views import logs_list

urlpatterns = [
    path("", logs_list, name="logs-list"),
]
