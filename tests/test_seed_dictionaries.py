import pytest
from django.core.management import call_command


pytestmark = pytest.mark.django_db


def test_seed_dictionaries_creates_default_records():
    from config.dictionaries.models import Currency, Country

    assert Currency.objects.count() == 0
    assert Country.objects.count() == 0

    call_command("seed_dictionaries")

    assert Currency.objects.filter(code="EUR").exists()
    assert Country.objects.filter(code="SK").exists()


def test_seed_dictionaries_is_idempotent():
    from config.dictionaries.models import Currency, Country

    call_command("seed_dictionaries")
    call_command("seed_dictionaries")

    assert Currency.objects.filter(code="EUR").count() == 1
    assert Country.objects.filter(code="SK").count() == 1
