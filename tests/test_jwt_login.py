import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model



pytestmark = pytest.mark.django_db


def test_jwt_login_returns_access_and_refresh(client):
    User = get_user_model()
    User.objects.create_user(email="a@example.com", password="pass12345")

    url = reverse("jwt-login")
    resp = client.post(
        url,
        data={"email": "a@example.com", "password": "pass12345"},
        content_type="application/json",
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "access" in data
    assert "refresh" in data
    assert isinstance(data["access"], str) and len(data["access"]) > 50
    assert isinstance(data["refresh"], str) and len(data["refresh"]) > 50


def test_jwt_login_wrong_password_returns_401(client):
    User = get_user_model()
    User.objects.create_user(email="a@example.com", password="pass12345")

    url = reverse("jwt-login")
    resp = client.post(
        url,
        data={"email": "a@example.com", "password": "wrong"},
        content_type="application/json",
    )

    assert resp.status_code in (400, 401)
