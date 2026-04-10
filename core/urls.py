# project/backend/core/urls.py

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from core.views import HealthView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health', HealthView.as_view(), name='health'),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/auth/", include("config.users.urls")),
    path("api/v1/dictionaries/", include("config.dictionaries.urls")),
    path("api/v1/orgs/", include("config.orgs.urls")),
    path("api/v1/partners/", include("apps.partners.urls")),
    path("api/v1/", include("apps.products.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("cashier/", include("apps.cashier.urls")),
    path("", include("apps.ops_dashboard.urls")),
    path("ops/logs/", include("apps.logs_dashboard.urls")),


]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
