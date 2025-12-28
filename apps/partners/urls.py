from django.urls import path
from .api_views import PartnerListCreateApi, PartnerDetailApi


urlpatterns = [
    path("", PartnerListCreateApi.as_view(), name="partners-list"),
    path("<uuid:public_id>/", PartnerDetailApi.as_view(), name="partner-detail"),
]
