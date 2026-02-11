import logging

import pytest

from apps.logs_dashboard.models import LogEntry
from config.observability.logging import DBLogHandler
from config.orgs.models import OrganizationMember
from config.orgs.models import Organization
from django.contrib.auth import get_user_model


@pytest.mark.django_db
def test_db_log_handler_persists_log_entry():
    logger = logging.getLogger("apps.test_logger")
    handler = DBLogHandler()

    record = logging.LogRecord(
        name="apps.test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='{"event":"test_event","message":"hello","org_id":"org-1"}',
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    entry = LogEntry.objects.first()
    assert entry is not None
    assert entry.event == "test_event"
    assert entry.message == "hello"
    assert entry.org_id == "org-1"


@pytest.mark.django_db
def test_logs_dashboard_uses_session_org_id(client, org_factory):
    User = get_user_model()
    user = User.objects.create_user(email="dash@example.com", password="pass12345")
    org = org_factory(name="Dash Org")
    OrganizationMember.objects.create(org=org, user=user, role=OrganizationMember.ROLE_ADMIN)

    client.force_login(user)
    session = client.session
    session["active_org_id"] = str(org.public_id)
    session.save()

    resp = client.get("/ops/logs/")
    assert resp.status_code == 200
