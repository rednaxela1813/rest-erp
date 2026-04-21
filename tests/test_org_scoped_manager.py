import pytest

from config.orgs.models import OrgNote


pytestmark = pytest.mark.django_db


def test_org_scoped_manager_for_org_returns_only_matching_records(org_factory):
    org_a = org_factory(name="Org A")
    org_b = org_factory(name="Org B")
    note_a = OrgNote.objects.create(org=org_a, title="A")
    OrgNote.objects.create(org=org_b, title="B")

    scoped = list(OrgNote.objects.for_org(org_a))

    assert scoped == [note_a]
