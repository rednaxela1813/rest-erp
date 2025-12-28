import pytest

pytestmark = pytest.mark.django_db


def test_org_note_list_is_scoped_by_x_org_id(auth_client, org_factory, member_factory, set_org_header):
    """
    Тест проверяет, что список заметок отфильтрован по активной организации (X-ORG-ID).
    """
    from config.orgs.models import OrgNote
    
    client, user = auth_client()
    
    org1 = org_factory(name="Org 1")
    org2 = org_factory(name="Org 2")
    member_factory(org=org1, user=user, role="member")
    member_factory(org=org2, user=user, role="member")

    OrgNote.objects.create(org=org1, title="A")
    OrgNote.objects.create(org=org2, title="B")

    set_org_header(client, org1)
    
    resp = client.get("/api/v1/orgs/notes/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "A"


def test_org_note_create_sets_org_from_header(admin_client):
    """
    Тест проверяет, что новая заметка создается в правильной организации.
    Используем admin_client, так как для создания заметок нужны права админа.
    """
    from config.orgs.models import OrgNote
    
    client, user, org = admin_client

    resp = client.post(
        "/api/v1/orgs/notes/",
        data={"title": "Hello"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert OrgNote.objects.filter(org=org, title="Hello").exists()
