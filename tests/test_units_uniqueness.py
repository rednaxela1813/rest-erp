import pytest

pytestmark = pytest.mark.django_db


def test_cannot_create_duplicate_active_unit_name_in_same_org(admin_client):
    client, admin, org = admin_client

    from apps.products.models import Unit
    Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)

    resp = client.post(
        "/api/v1/units/",
        data={"name": "pcs"},
        content_type="application/json",
    )
    # В DRF это обычно 400 с validation error
    assert resp.status_code == 400, resp.content


def test_can_recreate_unit_name_if_previous_is_archived(admin_client):
    client, admin, org = admin_client

    from apps.products.models import Unit

    u = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)

    # архивируем через API (как в реальной жизни)
    resp = client.delete(f"/api/v1/units/{u.public_id}/")
    assert resp.status_code in (204, 200), resp.content

    u.refresh_from_db()
    assert u.status == Unit.STATUS_ARCHIVED

    # теперь можно создать снова
    resp = client.post(
        "/api/v1/units/",
        data={"name": "pcs"},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
