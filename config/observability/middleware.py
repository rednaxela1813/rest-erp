import uuid

import structlog


class RequestContextMiddleware:
    """
    Adds request context to structured logs and sets X-Request-ID header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        org_id = request.headers.get("X-ORG-ID") or ""
        user_id = ""
        if hasattr(request, "user") and getattr(request.user, "is_authenticated", False):
            user_id = str(request.user.id)

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            org_id=org_id,
            user_id=user_id,
            path=request.path,
            method=request.method,
        )

        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        structlog.contextvars.clear_contextvars()
        return response
