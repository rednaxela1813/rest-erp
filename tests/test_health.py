import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_health_endpoint_returns_ok(client):
    url = reverse("health")
    resp = client.get(url)

    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/json")
    assert resp.json() == {"status": "ok"}
