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


def test_org_admin_cannot_add_missing_user(admin_client):
    client, admin, org = admin_client

    resp = client.post(
        "/api/v1/orgs/members/",
        data={
            "email": "missing@example.com",
            "role": "member",
        },
        content_type="application/json",
    )

    assert resp.status_code == 400, resp.content
    assert resp.json()["email"] == "User with this email does not exist."


def test_org_admin_cannot_add_duplicate_member(admin_client, user_factory, member_factory):
    client, admin, org = admin_client
    existing_user = user_factory(email="existing@example.com")
    member_factory(org=org, user=existing_user, role="member")

    resp = client.post(
        "/api/v1/orgs/members/",
        data={
            "email": "existing@example.com",
            "role": "member",
        },
        content_type="application/json",
    )

    assert resp.status_code == 400, resp.content
    assert resp.json()["email"] == "User is already a member of this organization."
