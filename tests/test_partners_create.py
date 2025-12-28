import pytest

pytestmark = pytest.mark.django_db


def test_org_admin_can_create_partner(admin_client):
    client, admin, org = admin_client

    resp = client.post(
        "/api/v1/partners/",
        data={"name": "ACME s.r.o."},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content

    data = resp.json()
    assert data["name"] == "ACME s.r.o."
    assert "public_id" in data

    from apps.partners.models import Partner
    assert Partner.objects.filter(org=org, name="ACME s.r.o.").exists()


def test_org_member_cannot_create_partner(member_client):
    client, user, org = member_client

    resp = client.post(
        "/api/v1/partners/",
        data={"name": "Nope"},
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_partner_is_created_in_active_org_not_from_body(admin_client, org_factory):
    client, admin, org_1 = admin_client
    org_2 = org_factory(name="Other Org")

    # даже если клиент попытается подсунуть org — мы игнорируем
    resp = client.post(
        "/api/v1/partners/",
        data={"name": "Scoped", "org": str(org_2.public_id)},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content

    from apps.partners.models import Partner
    assert Partner.objects.filter(org=org_1, name="Scoped").exists()
    assert not Partner.objects.filter(org=org_2, name="Scoped").exists()
