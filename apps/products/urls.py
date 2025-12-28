from django.urls import path
from .api_views import UnitListCreateApi, UnitDetailApi, TaxRateListApi

urlpatterns = [
    path("units/", UnitListCreateApi.as_view(), name="units"),
    path("units/<uuid:public_id>/", UnitDetailApi.as_view(), name="unit-detail"),
    path("tax-rates/", TaxRateListApi.as_view(), name="taxrates-list"),
    
]
