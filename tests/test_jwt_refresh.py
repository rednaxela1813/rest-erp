import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


pytestmark = pytest.mark.django_db


def test_jwt_refresh_returns_new_access(client):
    User = get_user_model()
    User.objects.create_user(email="a@example.com", password="pass12345")

    login_resp = client.post(
        reverse("jwt-login"),
        data={"email": "a@example.com", "password": "pass12345"},
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    refresh = login_resp.json()["refresh"]

    refresh_resp = client.post(
        reverse("jwt-refresh"),
        data={"refresh": refresh},
        content_type="application/json",
    )

    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert "access" in data
    assert isinstance(data["access"], str) and len(data["access"]) > 50
