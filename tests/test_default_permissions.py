import pytest


pytestmark = pytest.mark.django_db


def test_tax_rates_endpoint_requires_authentication(client):
    response = client.get("/api/v1/tax-rates/")

    assert response.status_code == 401
