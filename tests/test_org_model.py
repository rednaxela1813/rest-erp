import pytest

pytestmark = pytest.mark.django_db



def test_org_has_public_id_uuid():
    from config.orgs.models import Organization

    org = Organization.objects.create(name="Deilmann s.r.o.")
    assert org.public_id is not None
    assert len(str(org.public_id)) == 36


def test_org_str_returns_name():
    from config.orgs.models import Organization

    org = Organization.objects.create(name="Deilmann s.r.o.")
    assert str(org) == "Deilmann s.r.o."
