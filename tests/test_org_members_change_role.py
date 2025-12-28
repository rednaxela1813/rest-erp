import pytest

pytestmark = pytest.mark.django_db


def test_org_admin_can_change_member_role(admin_client, user_factory, member_factory):
    client, admin, org = admin_client

    u = user_factory(email="u1@example.com")
    m = member_factory(org=org, user=u, role="member")

    resp = client.patch(
        f"/api/v1/orgs/members/{m.id}/",
        data={"role": "admin"},
        content_type="application/json",
    )

    assert resp.status_code == 200, resp.content

    from config.orgs.models import OrganizationMember
    m.refresh_from_db()
    assert m.role == "admin"
    assert OrganizationMember.objects.get(id=m.id).role == "admin"


def test_org_member_cannot_change_roles(member_client, user_factory, member_factory):
    client, member, org = member_client

    u = user_factory(email="u2@example.com")
    m = member_factory(org=org, user=u, role="member")

    resp = client.patch(
        f"/api/v1/orgs/members/{m.id}/",
        data={"role": "admin"},
        content_type="application/json",
    )

    assert resp.status_code == 403


def test_cannot_change_member_from_other_org(admin_client, org_factory, user_factory, member_factory):
    client, admin, org_1 = admin_client

    org_2 = org_factory(name="Other Org")
    u = user_factory(email="x@example.com")
    m_other = member_factory(org=org_2, user=u, role="member")

    # Пытаемся менять участника другой org через активный X-ORG-ID org_1
    resp = client.patch(
        f"/api/v1/orgs/members/{m_other.id}/",
        data={"role": "admin"},
        content_type="application/json",
    )

    # мы “прячем” факт существования чужой записи: 404 предпочтительнее
    assert resp.status_code == 404
