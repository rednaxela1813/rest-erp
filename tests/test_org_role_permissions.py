import pytest

pytestmark = pytest.mark.django_db


def test_member_can_list_but_cannot_create(member_client):
    """
    Тест проверяет, что обычный участник может читать, но не может создавать заметки.
    """
    client, user, org = member_client

    # list ok
    resp = client.get("/api/v1/orgs/notes/")
    assert resp.status_code == 200

    # create forbidden
    resp = client.post(
        "/api/v1/orgs/notes/",
        data={"title": "Nope"},
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_admin_can_create(admin_client):
    """
    Тест проверяет, что админ может создавать заметки.
    """
    client, user, org = admin_client

    resp = client.post(
        "/api/v1/orgs/notes/",
        data={"title": "Ok"},
        content_type="application/json",
    )
    assert resp.status_code == 201
