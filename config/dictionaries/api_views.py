from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from .models import Country, Currency
from .serializers import CountrySerializer, CurrencySerializer


class CurrencyListView(ListAPIView):
    # intentionally public: cashier/bootstrap clients need currency metadata before user login
    permission_classes = [AllowAny]
    queryset = Currency.objects.all()
    serializer_class = CurrencySerializer


class CountryListView(ListAPIView):
    # intentionally public: country dictionary is safe read-only reference data
    permission_classes = [AllowAny]
    queryset = Country.objects.all()
    serializer_class = CountrySerializer
