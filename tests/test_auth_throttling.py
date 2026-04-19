import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse


pytestmark = pytest.mark.django_db


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": (
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ),
        "DEFAULT_THROTTLE_CLASSES": [
            "rest_framework.throttling.AnonRateThrottle",
            "rest_framework.throttling.UserRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "anon": "100/hour",
            "user": "1000/hour",
            "login": "5/min",
        },
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    }
)
def test_login_is_rate_limited_after_five_requests(client):
    cache.clear()
    User = get_user_model()
    User.objects.create_user(email="a@example.com", password="pass12345")

    url = reverse("jwt-login")
    last_response = None
    for _ in range(5):
        last_response = client.post(
            url,
            data={"email": "a@example.com", "password": "wrong"},
            content_type="application/json",
        )

    assert last_response is not None
    assert last_response.status_code in (400, 401)

    throttled_response = client.post(
        url,
        data={"email": "a@example.com", "password": "wrong"},
        content_type="application/json",
    )

    assert throttled_response.status_code == 429
