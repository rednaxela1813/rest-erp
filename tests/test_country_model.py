import pytest
from django.db import IntegrityError



pytestmark = pytest.mark.django_db


def test_country_str_returns_code():
    from config.dictionaries.models import Country

    sk = Country.objects.create(code="SK", name="Slovakia")
    assert str(sk) == "SK"


def test_country_code_unique():
    from config.dictionaries.models import Country

    Country.objects.create(code="SK", name="Slovakia")

    with pytest.raises(IntegrityError):
        Country.objects.create(code="SK", name="Slovak Republic")
