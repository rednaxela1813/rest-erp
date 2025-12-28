# tests/conftest.py
import uuid
import pytest
from django.contrib.auth import get_user_model


# === НАСТРОЙКА: подстрой под твои URL, если отличаются ===
JWT_LOGIN_URL = "/api/v1/auth/login/"  # поменяй, если у тебя другой


@pytest.fixture
def user_factory(db):
    """
    Создаёт пользователя с заданным email/паролем.
    Возвращает объект user.
    """
    def _make_user(email: str, password: str = "pass12345", **kwargs):
        User = get_user_model()

        # если у тебя есть create_user(email=...), используем его
        if hasattr(User.objects, "create_user"):
            user = User.objects.create_user(email=email, password=password, **kwargs)
        else:
            user = User(email=email, **kwargs)
            user.set_password(password)
            user.save()

        return user

    return _make_user


@pytest.fixture
def api_client(client, db):
    """
    Django test client (как обычно), но оставляем именование "api_client",
    чтобы было понятно, что это клиент для HTTP-запросов к API.
    """
    return client


@pytest.fixture
def auth_client(api_client, user_factory):
    """
    Возвращает (client, user) с установленным Authorization: Bearer <access>.
    Аутентификация строго как в проде — через JWT login endpoint.
    """
    def _login(email: str = "a@example.com", password: str = "pass12345", **user_kwargs):
        user = user_factory(email=email, password=password, **user_kwargs)

        resp = api_client.post(
            JWT_LOGIN_URL,
            data={"email": email, "password": password},
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content

        payload = resp.json()
        access = payload.get("access")
        assert access, f"Login response has no 'access' token. Got: {payload}"

        api_client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access}"
        return api_client, user

    return _login


@pytest.fixture
def org_factory(db):
    from config.orgs.models import Organization

    def _make_org(name: str = "Org 1", **kwargs):
        return Organization.objects.create(name=name, **kwargs)

    return _make_org


@pytest.fixture
def member_factory(db):
    from config.orgs.models import OrganizationMember

    def _make_member(org, user, role: str = "member", **kwargs):
        return OrganizationMember.objects.create(org=org, user=user, role=role, **kwargs)

    return _make_member


@pytest.fixture
def set_org_header():
    """
    Устанавливает активную org в клиент через X-ORG-ID.
    """
    def _set(client, org):
        # Django test client читает заголовки так:
        # X-ORG-ID -> HTTP_X_ORG_ID
        client.defaults["HTTP_X_ORG_ID"] = str(org.public_id)
        return client

    return _set


# === УДОБНЫЕ ГОТОВЫЕ ФИКСТУРЫ ДЛЯ РОЛЕЙ ===

@pytest.fixture
def owner_client(auth_client, org_factory, member_factory, set_org_header):
    """
    (client, user, org) где user = owner в org и X-ORG-ID уже установлен.
    """
    client, user = auth_client(email="owner@example.com")
    org = org_factory(name="Owner Org")
    member_factory(org=org, user=user, role="owner")
    set_org_header(client, org)
    return client, user, org


@pytest.fixture
def admin_client(auth_client, org_factory, member_factory, set_org_header):
    client, user = auth_client(email="admin@example.com")
    org = org_factory(name="Admin Org")
    member_factory(org=org, user=user, role="admin")
    set_org_header(client, org)
    return client, user, org


@pytest.fixture
def member_client(auth_client, org_factory, member_factory, set_org_header):
    client, user = auth_client(email="member@example.com")
    org = org_factory(name="Member Org")
    member_factory(org=org, user=user, role="member")
    set_org_header(client, org)
    return client, user, org


from apps.payments.models import OrderPayment

def create_captured_payment_for_order(*, org, order, amount=None):
    order.refresh_from_db()
    return OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CASH,
        status=OrderPayment.Status.CAPTURED,
        amount=amount if amount is not None else order.total,
        currency="EUR",
        provider="manual",
    )
