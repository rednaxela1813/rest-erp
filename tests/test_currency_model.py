import pytest
from django.db import IntegrityError


pytestmark = pytest.mark.django_db


def test_currency_str_returns_code():
    from config.dictionaries.models import Currency

    c = Currency.objects.create(code="EUR", name="Euro", symbol="€")
    assert str(c) == "EUR"


def test_currency_code_unique():
    from config.dictionaries.models import Currency

    Currency.objects.create(code="EUR", name="Euro", symbol="€")

    with pytest.raises(IntegrityError):
        Currency.objects.create(code="EUR", name="Euro 2", symbol="€")
