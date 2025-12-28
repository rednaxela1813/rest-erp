import pytest
from django.db import IntegrityError
from django.contrib.auth import get_user_model


pytestmark = pytest.mark.django_db


def test_member_unique_per_org_and_user():
    from config.orgs.models import Organization, OrganizationMember

    User = get_user_model()
    user = User.objects.create_user(email="a@example.com", password="pass12345")
    org = Organization.objects.create(name="Deilmann s.r.o.")

    OrganizationMember.objects.create(org=org, user=user, role="owner")

    with pytest.raises(IntegrityError):
        OrganizationMember.objects.create(org=org, user=user, role="member")


def test_member_str_contains_org_and_email():
    from config.orgs.models import Organization, OrganizationMember

    User = get_user_model()
    user = User.objects.create_user(email="a@example.com", password="pass12345")
    org = Organization.objects.create(name="Deilmann s.r.o.")

    m = OrganizationMember.objects.create(org=org, user=user, role="owner")

    s = str(m)
    assert "Deilmann" in s
    assert "a@example.com" in s
