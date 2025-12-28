import pytest

pytestmark = pytest.mark.django_db


def test_cannot_delete_last_owner(owner_client):
    client, owner, org = owner_client

    # В org только один участник-owner (это owner_client fixture)
    # Пытаемся удалить самого себя => должно быть запрещено
    # (формально правило "нельзя удалить последнего owner")
    from config.orgs.models import OrganizationMember

    me = OrganizationMember.objects.get(org=org, user=owner)

    resp = client.delete(f"/api/v1/orgs/members/{me.id}/")
    assert resp.status_code == 400, resp.content

    me.refresh_from_db()
    assert me.role == "owner"
    

def test_cannot_demote_last_owner(owner_client):
    client, owner, org = owner_client

    from config.orgs.models import OrganizationMember

    me = OrganizationMember.objects.get(org=org, user=owner)

    resp = client.patch(
        f"/api/v1/orgs/members/{me.id}/",
        data={"role": "admin"},
        content_type="application/json",
    )
    assert resp.status_code == 400, resp.content

    me.refresh_from_db()
    assert me.role == "owner"
    
    
def test_admin_cannot_change_owner_role(admin_client, user_factory, member_factory):
    client, admin, org = admin_client

    owner1 = user_factory(email="owner1@example.com")
    owner2 = user_factory(email="owner2@example.com")
    m1 = member_factory(org=org, user=owner1, role="owner")
    member_factory(org=org, user=owner2, role="owner")  # второй owner => last-owner guard не мешает

    resp = client.patch(
        f"/api/v1/orgs/members/{m1.id}/",
        data={"role": "admin"},
        content_type="application/json",
    )

    assert resp.status_code == 403, resp.content

    m1.refresh_from_db()
    assert m1.role == "owner"