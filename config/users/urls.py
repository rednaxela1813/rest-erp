from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .api_views import MeView, LogoutView

urlpatterns = [
    path("login/", TokenObtainPairView.as_view(), name="jwt-login"),
    path("refresh/", TokenRefreshView.as_view(), name="jwt-refresh"),
    path("logout/", LogoutView.as_view(), name="jwt-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
]
