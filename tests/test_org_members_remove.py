import pytest

pytestmark = pytest.mark.django_db


def test_org_admin_can_remove_member(admin_client, user_factory, member_factory):
    client, admin, org = admin_client

    u = user_factory(email="del@example.com")
    m = member_factory(org=org, user=u, role="member")

    resp = client.delete(f"/api/v1/orgs/members/{m.id}/")
    assert resp.status_code in (204, 200), resp.content

    from config.orgs.models import OrganizationMember
    assert not OrganizationMember.objects.filter(id=m.id).exists()


def test_org_member_cannot_remove_member(member_client, user_factory, member_factory):
    client, member, org = member_client

    u = user_factory(email="del2@example.com")
    m = member_factory(org=org, user=u, role="member")

    resp = client.delete(f"/api/v1/orgs/members/{m.id}/")
    assert resp.status_code == 403


def test_cannot_remove_member_from_other_org(admin_client, org_factory, user_factory, member_factory):
    client, admin, org_1 = admin_client

    org_2 = org_factory(name="Other Org")
    u = user_factory(email="outsider_del@example.com")
    m_other = member_factory(org=org_2, user=u, role="member")

    resp = client.delete(f"/api/v1/orgs/members/{m_other.id}/")
    assert resp.status_code == 404
