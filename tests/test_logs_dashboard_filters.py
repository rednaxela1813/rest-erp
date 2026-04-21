from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.logs_dashboard.models import LogEntry
from apps.logs_dashboard.tasks import purge_old_logs
from config.orgs.models import OrganizationMember


@pytest.mark.django_db
def test_logs_dashboard_filters_and_csv(client, org_factory):
    User = get_user_model()
    user = User.objects.create_user(email="filters@example.com", password="pass12345")
    org = org_factory(name="Filter Org")
    OrganizationMember.objects.create(org=org, user=user, role=OrganizationMember.ROLE_ADMIN)

    LogEntry.objects.create(
        level="INFO",
        event="payment_capture_started",
        message="Payment started",
        org_id=str(org.public_id),
        request_id="req-1",
        path="/api/v1/payments/",
        method="POST",
    )
    LogEntry.objects.create(
        level="ERROR",
        event="ekasa_failed",
        message="eKasa failed",
        org_id=str(org.public_id),
        request_id="req-2",
        path="/api/v1/health/ekasa/",
        method="GET",
    )

    client.force_login(user)
    session = client.session
    session["active_org_id"] = str(org.public_id)
    session.save()

    resp = client.get("/ops/logs/?level=ERROR")
    assert resp.status_code == 200
    assert b"ekasa_failed" in resp.content
    assert b"payment_capture_started" not in resp.content

    csv_resp = client.get("/ops/logs/?format=csv")
    assert csv_resp.status_code == 200
    assert csv_resp["Content-Type"] == "text/csv"
    assert b"created_at,level,event,message" in csv_resp.content

    task_resp = client.get("/ops/logs/?task_name=ekasa")
    assert task_resp.status_code == 200


@pytest.mark.django_db
def test_purge_old_logs_deletes_entries(org_factory):
    org = org_factory(name="Retention Org")
    old_entry = LogEntry.objects.create(
        level="INFO",
        event="old",
        message="old",
        org_id=str(org.public_id),
    )
    LogEntry.objects.filter(id=old_entry.id).update(created_at=timezone.now() - timedelta(days=40))
    LogEntry.objects.create(
        level="INFO",
        event="new",
        message="new",
        org_id=str(org.public_id),
    )

    result = purge_old_logs.run(days=30)
    assert result["deleted"] >= 1
    assert LogEntry.objects.filter(event="old").count() == 0
    assert LogEntry.objects.filter(event="new").count() == 1
