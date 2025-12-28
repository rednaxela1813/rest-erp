import pytest

pytestmark = pytest.mark.django_db


def test_org_admin_can_create_unit(admin_client):
    client, admin, org = admin_client

    resp = client.post(
        "/api/v1/units/",
        data={"name": "pcs"},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content

    data = resp.json()
    assert data["name"] == "pcs"
    assert "public_id" in data
    assert "id" not in data

    from apps.products.models import Unit
    assert Unit.objects.filter(org=org, name="pcs", status=Unit.STATUS_ACTIVE).exists()


def test_org_member_cannot_create_unit(member_client):
    client, user, org = member_client

    resp = client.post(
        "/api/v1/units/",
        data={"name": "kg"},
        content_type="application/json",
    )
    assert resp.status_code == 403
