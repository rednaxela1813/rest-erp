from django.urls import path

from .api_views import CountryListView, CurrencyListView


urlpatterns = [
    path("currencies/", CurrencyListView.as_view(), name="currencies-list"),
    path("countries/", CountryListView.as_view(), name="countries-list"),
]
