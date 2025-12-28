import pytest

pytestmark = pytest.mark.django_db


def test_taxrates_list_is_org_scoped_and_uses_public_id(member_client, org_factory):
    client, user, org_1 = member_client
    org_2 = org_factory(name="Other Org")

    from apps.products.models import TaxRate

    t1 = TaxRate.objects.create(org=org_1, name="DPH 20%", rate=20, status=TaxRate.STATUS_ACTIVE)
    t2 = TaxRate.objects.create(org=org_1, name="DPH 10%", rate=10, status=TaxRate.STATUS_ACTIVE)
    TaxRate.objects.create(org=org_2, name="Other 5%", rate=5, status=TaxRate.STATUS_ACTIVE)

    resp = client.get("/api/v1/tax-rates/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data

    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"DPH 20%", "DPH 10%"}

    public_ids = {i["public_id"] for i in items}
    assert str(t1.public_id) in public_ids
    assert str(t2.public_id) in public_ids

    assert "id" not in items[0]
