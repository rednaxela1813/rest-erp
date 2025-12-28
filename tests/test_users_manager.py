import pytest
from django.contrib.auth.hashers import check_password

pytestmark = pytest.mark.django_db


def test_create_user_requires_email():
    from config.users.models import User

    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="pass12345")


def test_create_user_normalizes_email():
    from config.users.models import User

    user = User.objects.create_user(email="TEST@Example.COM", password="pass12345")
    assert user.email == "TEST@example.com"


def test_create_user_hashes_password():
    from config.users.models import User

    user = User.objects.create_user(email="a@example.com", password="pass12345")

    assert user.password != "pass12345"
    assert check_password("pass12345", user.password) is True


def test_create_superuser_sets_flags():
    from config.users.models import User

    admin = User.objects.create_superuser(email="admin@example.com", password="pass12345")

    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert admin.is_active is True
