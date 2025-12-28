import pytest

pytestmark = pytest.mark.django_db


def test_org_members_list_returns_only_members_of_active_org(
    auth_client, org_factory, member_factory, user_factory, set_org_header
):
    """
    Тест проверяет, что API /api/v1/orgs/members/ возвращает только участников активной организации.
    """
    # Создаем клиента с аутентификацией
    client, me = auth_client(email="a@example.com")
    
    # org_1 (активная)
    org_1 = org_factory(name="Org 1")
    member_factory(org=org_1, user=me, role="member")
    
    # Создаем еще одного участника org_1
    other_1 = user_factory(email="b@example.com", password="pass12345")
    member_factory(org=org_1, user=other_1, role="admin")
    
    # org_2 (чужая)
    org_2 = org_factory(name="Org 2")
    outsider = user_factory(email="c@example.com", password="pass12345")
    member_factory(org=org_2, user=outsider, role="owner")
    
    # Устанавливаем активную организацию
    set_org_header(client, org_1)
    
    resp = client.get("/api/v1/orgs/members/")
    
    assert resp.status_code == 200, resp.content
    
    data = resp.json()
    
    # допускаем два формата: либо пагинация DRF, либо простой список
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    
    assert isinstance(items, list)
    assert len(items) == 2
    
    emails = {item.get("email") or (item.get("user") or {}).get("email") for item in items}
    roles = {item.get("role") for item in items}
    
    # проверяем, что оба участника org_1 на месте
    assert "a@example.com" in emails
    assert "b@example.com" in emails
    
    # и что участник org_2 не пролез
    assert "c@example.com" not in emails
    
    # роли тоже должны быть
    assert "member" in roles
    assert "admin" in roles
