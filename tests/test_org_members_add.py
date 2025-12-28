import pytest

pytestmark = pytest.mark.django_db


def test_org_admin_can_add_member(
    admin_client, user_factory, member_factory
):
    client, admin, org = admin_client

    new_user = user_factory(email="new@example.com")

    resp = client.post(
        "/api/v1/orgs/members/",
        data={
            "email": "new@example.com",
            "role": "member",
        },
        content_type="application/json",
    )

    assert resp.status_code == 201, resp.content

    from config.orgs.models import OrganizationMember

    assert OrganizationMember.objects.filter(
        org=org,
        user=new_user,
        role="member",
    ).exists()


def test_org_member_cannot_add_member(
    member_client, user_factory
):
    client, member, org = member_client

    user_factory(email="evil@example.com")

    resp = client.post(
        "/api/v1/orgs/members/",
        data={
            "email": "evil@example.com",
            "role": "member",
        },
        content_type="application/json",
    )

    assert resp.status_code == 403

