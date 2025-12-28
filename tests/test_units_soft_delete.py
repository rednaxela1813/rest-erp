import pytest

pytestmark = pytest.mark.django_db


def test_delete_archives_unit_and_list_hides_it(admin_client):
    client, admin, org = admin_client

    from apps.products.models import Unit
    u = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)

    resp = client.delete(f"/api/v1/units/{u.public_id}/")
    assert resp.status_code in (204, 200), resp.content

    u.refresh_from_db()
    assert u.status == Unit.STATUS_ARCHIVED

    resp = client.get("/api/v1/units/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    names = {i["name"] for i in items}
    assert "pcs" not in names
