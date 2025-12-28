import pytest

pytestmark = pytest.mark.django_db


def test_partners_list_is_org_scoped(member_client, org_factory):
    client, user, org_1 = member_client
    org_2 = org_factory(name="Other Org")

    from apps.partners.models import Partner

    p1 = Partner.objects.create(org=org_1, name="Partner A")
    p2 = Partner.objects.create(org=org_1, name="Partner B")
    Partner.objects.create(org=org_2, name="Partner X")

    resp = client.get("/api/v1/partners/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data

    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"Partner A", "Partner B"}

    public_ids = {i["public_id"] for i in items}
    assert str(p1.public_id) in public_ids
    assert str(p2.public_id) in public_ids

    # важная проверка: публично не светим внутренний id
    assert "id" not in items[0]
