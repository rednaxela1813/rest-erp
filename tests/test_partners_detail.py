import pytest

pytestmark = pytest.mark.django_db


def test_admin_can_update_partner_name(admin_client):
    client, admin, org = admin_client

    from apps.partners.models import Partner
    p = Partner.objects.create(org=org, name="Old")

    resp = client.patch(
        f"/api/v1/partners/{p.public_id}/",
        data={"name": "New"},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content

    p.refresh_from_db()
    assert p.name == "New"


def test_member_cannot_update_partner(member_client):
    client, user, org = member_client

    from apps.partners.models import Partner
    p = Partner.objects.create(org=org, name="Old")

    resp = client.patch(
        f"/api/v1/partners/{p.public_id}/",
        data={"name": "New"},
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_admin_can_delete_partner(admin_client):
    client, admin, org = admin_client

    from apps.partners.models import Partner
    p = Partner.objects.create(org=org, name="To delete")

    resp = client.delete(f"/api/v1/partners/{p.public_id}/")
    assert resp.status_code in (204, 200), resp.content

    p.refresh_from_db()
    assert p.status == Partner.STATUS_ARCHIVED


def test_cannot_access_partner_from_other_org(admin_client, org_factory):
    client, admin, org_1 = admin_client
    org_2 = org_factory(name="Other Org")

    from apps.partners.models import Partner
    p_other = Partner.objects.create(org=org_2, name="Other")

    resp = client.patch(
        f"/api/v1/partners/{p_other.public_id}/",
        data={"name": "Hacked"},
        content_type="application/json",
    )
    assert resp.status_code == 404
