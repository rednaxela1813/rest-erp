from django.urls import path

from .api_views import LoginView, LogoutView, MeView, RefreshView

urlpatterns = [
    path("login/", LoginView.as_view(), name="jwt-login"),
    path("refresh/", RefreshView.as_view(), name="jwt-refresh"),
    path("logout/", LogoutView.as_view(), name="jwt-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
]
