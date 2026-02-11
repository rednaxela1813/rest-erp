import re

import pytest


@pytest.mark.django_db
def test_request_context_middleware_sets_request_id_header(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    request_id = resp.headers.get("X-Request-ID")
    assert request_id is not None
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
