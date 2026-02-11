from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment


@pytest.mark.django_db
def test_ops_dashboard_requires_admin(owner_client):
    owner, owner_user, owner_org = owner_client
    owner.force_login(owner_user)

    resp_redirect = owner.get("/dashboard/")
    assert resp_redirect.status_code == 200

    resp = owner.get(f"/dashboard/?org={owner_org.public_id}")
    assert resp.status_code == 200
    assert b"Operations Dashboard" in resp.content

    # Downgrade role to member and verify access is denied.
    from config.orgs.models import OrganizationMember

    membership = OrganizationMember.objects.get(org=owner_org, user=owner_user)
    membership.role = OrganizationMember.ROLE_MEMBER
    membership.save(update_fields=["role"])

    resp_forbidden = owner.get(f"/dashboard/?org={owner_org.public_id}")
    assert resp_forbidden.status_code == 403


@pytest.mark.django_db
def test_ops_dashboard_metrics_counts(admin_client):
    client, user, org = admin_client
    client.force_login(user)

    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
        capture_status=OrderPayment.CaptureStatus.TIMEOUT,
    )

    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.PENDING,
        idempotency_key="dash:fiscal",
    )

    resp = client.get(f"/dashboard/metrics/?org={org.public_id}")
    assert resp.status_code == 200
    assert b"Unsent fiscal receipts" in resp.content


@pytest.mark.django_db
def test_ops_dashboard_management_tab(admin_client):
    client, user, org = admin_client
    client.force_login(user)

    resp = client.get(f"/dashboard/?org={org.public_id}")
    assert resp.status_code == 200
    assert b"Management" in resp.content
