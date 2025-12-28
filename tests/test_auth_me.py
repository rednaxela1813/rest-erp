import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


pytestmark = pytest.mark.django_db


def test_auth_me_requires_token(client):
    # Без токена должно быть 401
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 401


def test_auth_me_returns_current_user(client):
    User = get_user_model()
    user = User.objects.create_user(email="me@example.com", password="pass12345")

    # 1) логинимся и получаем access
    login_url = reverse("jwt-login")
    login_resp = client.post(
        login_url,
        data={"email": "me@example.com", "password": "pass12345"},
        content_type="application/json",
    )
    assert login_resp.status_code == 200
    access = login_resp.json()["access"]

    # 2) дергаем /me/ с токеном
    resp = client.get(
        "/api/v1/auth/me/",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )

    assert resp.status_code == 200
    data = resp.json()

    # Минимальный контракт (пока без ролей/организаций)
    assert data["email"] == user.email
