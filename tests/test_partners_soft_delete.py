import pytest

pytestmark = pytest.mark.django_db


def test_delete_archives_partner_and_list_hides_it(admin_client):
    client, admin, org = admin_client

    from apps.partners.models import Partner
    p = Partner.objects.create(org=org, name="To archive")

    resp = client.delete(f"/api/v1/partners/{p.public_id}/")
    assert resp.status_code in (204, 200), resp.content

    p.refresh_from_db()
    assert p.status == Partner.STATUS_ARCHIVED

    resp = client.get("/api/v1/partners/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    names = {i["name"] for i in items}

    assert "To archive" not in names
