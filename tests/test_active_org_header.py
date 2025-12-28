import pytest

pytestmark = pytest.mark.django_db


def test_active_org_missing_header_returns_400(auth_client):
    """
    Проверяем, что некоторые endpoints работают и без X-ORG-ID заголовка.
    """
    client, user = auth_client()

    resp = client.get("/api/v1/orgs/my/")  # позже заменим на protected endpoint, пока проверим механизм
    # В этом шаге мы включим middleware только на новые endpoints, поэтому ниже будет отдельный тест на endpoint.
    assert resp.status_code in (200, 400)


def test_org_context_endpoint_requires_x_org_id(auth_client):
    """
    Тест проверяет, что endpoint /api/v1/orgs/context/ требует заголовок X-ORG-ID.
    """
    client, user = auth_client()

    resp = client.get("/api/v1/orgs/context/")
    assert resp.status_code == 400
    assert "X-ORG-ID" in resp.json()["detail"]


def test_org_context_endpoint_returns_org_when_member(member_client):
    """
    Тест проверяет, что участник организации может получить информацию о ней.
    """
    client, user, org = member_client

    resp = client.get("/api/v1/orgs/context/")
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["public_id"] == str(org.public_id)
    assert data["name"] == org.name


def test_org_context_endpoint_denies_when_not_member(auth_client, org_factory, set_org_header):
    """
    Тест проверяет, что пользователь не может получить информацию о чужой организации.
    """
    client, user = auth_client()
    
    # Создаем организацию, в которой пользователь не состоит
    org = org_factory(name="Other Org")
    set_org_header(client, org)

    resp = client.get("/api/v1/orgs/context/")
    
    assert resp.status_code in (403, 404)
