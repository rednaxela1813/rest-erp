from datetime import date

import pytest

from apps.equipment.models import Equipment


pytestmark = pytest.mark.django_db


def test_equipment_next_maintenance_date(org_factory):
    org = org_factory()
    equipment = Equipment.objects.create(
        org=org,
        name="Fridge",
        last_maintenance_date=date(2026, 1, 15),
        maintenance_interval_months=3,
    )

    assert equipment.next_maintenance_date() == date(2026, 4, 15)


def test_equipment_next_maintenance_date_returns_none_without_schedule(org_factory):
    org = org_factory()
    equipment = Equipment.objects.create(org=org, name="Fridge")

    assert equipment.next_maintenance_date() is None


def test_equipment_str_returns_name(org_factory):
    org = org_factory()
    equipment = Equipment.objects.create(org=org, name="Fridge")

    assert str(equipment) == "Fridge"
