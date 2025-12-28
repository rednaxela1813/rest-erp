import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


pytestmark = pytest.mark.django_db


def test_logout_blacklists_refresh_token(client):
    User = get_user_model()
    User.objects.create_user(email="a@example.com", password="pass12345")

    login_resp = client.post(
        reverse("jwt-login"),
        data={"email": "a@example.com", "password": "pass12345"},
        content_type="application/json",
    )
    refresh = login_resp.json()["refresh"]

    # logout -> должен принять refresh и занести его в blacklist
    logout_resp = client.post(
        reverse("jwt-logout"),
        data={"refresh": refresh},
        content_type="application/json",
    )
    assert logout_resp.status_code == 205  # Reset Content (часто используют) или 200 — см. реализацию

    # попытка refresh этим токеном теперь должна быть запрещена
    refresh_resp = client.post(
        reverse("jwt-refresh"),
        data={"refresh": refresh},
        content_type="application/json",
    )
    assert refresh_resp.status_code in (401, 400)
