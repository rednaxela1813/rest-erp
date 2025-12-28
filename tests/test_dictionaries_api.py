import pytest


pytestmark = pytest.mark.django_db


def test_list_currencies_returns_items(client):
    from config.dictionaries.models import Currency

    Currency.objects.create(code="EUR", name="Euro", symbol="€")

    resp = client.get("/api/v1/dictionaries/currencies/")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["code"] == "EUR"
    assert data[0]["name"] == "Euro"
    assert data[0]["symbol"] == "€"


def test_list_countries_returns_items(client):
    from config.dictionaries.models import Country

    Country.objects.create(code="SK", name="Slovakia")

    resp = client.get("/api/v1/dictionaries/countries/")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["code"] == "SK"
    assert data[0]["name"] == "Slovakia"
