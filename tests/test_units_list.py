import pytest

pytestmark = pytest.mark.django_db


def test_units_list_is_org_scoped_and_uses_public_id(member_client, org_factory):
    client, user, org_1 = member_client
    org_2 = org_factory(name="Other Org")

    from apps.products.models import Unit

    u1 = Unit.objects.create(org=org_1, name="pcs", status=Unit.STATUS_ACTIVE)
    u2 = Unit.objects.create(org=org_1, name="kg", status=Unit.STATUS_ACTIVE)
    Unit.objects.create(org=org_2, name="hour", status=Unit.STATUS_ACTIVE)

    resp = client.get("/api/v1/units/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data

    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"pcs", "kg"}

    public_ids = {i["public_id"] for i in items}
    assert str(u1.public_id) in public_ids
    assert str(u2.public_id) in public_ids

    assert "id" not in items[0]
