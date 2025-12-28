import pytest

pytestmark = pytest.mark.django_db


def test_my_orgs_requires_auth(api_client):
    """
    Тест проверяет, что endpoint /api/v1/orgs/my/ требует аутентификации.
    """
    resp = api_client.get("/api/v1/orgs/my/")
    assert resp.status_code == 401


def test_create_org_creates_owner_membership(auth_client):
    """
    Тест проверяет, что при создании организации создается членство с ролью owner.
    """
    client, user = auth_client()

    resp = client.post(
        "/api/v1/orgs/",
        data={"name": "Deilmann s.r.o.", "legal_form": "s.r.o."},
        content_type="application/json",
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["name"] == "Deilmann s.r.o."
    assert data["legal_form"] == "s.r.o."
    assert "public_id" in data

    # проверяем в базе membership owner
    from config.orgs.models import Organization, OrganizationMember
    org = Organization.objects.get(public_id=data["public_id"])
    m = OrganizationMember.objects.get(org=org)
    assert m.role == "owner"


def test_my_orgs_returns_only_user_orgs(auth_client, org_factory, member_factory, user_factory):
    """
    Тест проверяет, что API возвращает только организации текущего пользователя.
    """
    client, u1 = auth_client(email="a@example.com")
    u2 = user_factory(email="b@example.com", password="pass12345")

    org1 = org_factory(name="Org 1")
    org2 = org_factory(name="Org 2")

    member_factory(org=org1, user=u1, role="member")
    member_factory(org=org2, user=u2, role="member")

    resp = client.get("/api/v1/orgs/my/")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "Org 1"
