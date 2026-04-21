import pytest

from config.orgs.middleware import set_active_org_id


pytestmark = pytest.mark.django_db


class StubLogger:
    def __init__(self):
        self.events = []

    def info(self, event, **kwargs):
        self.events.append((event, kwargs))


def test_set_active_org_id_logs_when_value_changes(rf, monkeypatch):
    request = rf.get("/")
    request.session = {}
    request.user = type("User", (), {"id": 42})()
    stub = StubLogger()

    monkeypatch.setattr("config.orgs.middleware.logger", stub)

    set_active_org_id(request, "org-1", source="test")

    assert request.session["active_org_id"] == "org-1"
    assert stub.events == [
        (
            "active_org_id_changed",
            {
                "user_id": "42",
                "previous_org_id": "",
                "org_id": "org-1",
                "source": "test",
            },
        )
    ]


def test_set_active_org_id_skips_log_for_same_value(rf, monkeypatch):
    request = rf.get("/")
    request.session = {"active_org_id": "org-1"}
    request.user = type("User", (), {"id": 42})()
    stub = StubLogger()

    monkeypatch.setattr("config.orgs.middleware.logger", stub)

    set_active_org_id(request, "org-1", source="test")

    assert request.session["active_org_id"] == "org-1"
    assert stub.events == []
