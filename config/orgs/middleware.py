import structlog
from django.utils.deprecation import MiddlewareMixin


logger = structlog.get_logger(__name__)


class SessionOrgMiddleware(MiddlewareMixin):
    """
    If X-ORG-ID header is missing, try to pull org from session.
    """

    SESSION_ACTIVE_ORG_ID = "active_org_id"

    def process_request(self, request):
        # Avoid request.headers to prevent header cache from locking stale values.
        if request.META.get("HTTP_X_ORG_ID"):
            return None
        org_id = request.session.get(self.SESSION_ACTIVE_ORG_ID)
        if org_id:
            request.META["HTTP_X_ORG_ID"] = org_id
            # Clear cached headers if already computed.
            if hasattr(request, "_headers"):
                delattr(request, "_headers")
        return None


def set_active_org_id(request, org_id: str, *, source: str) -> None:
    previous_org_id = request.session.get(SessionOrgMiddleware.SESSION_ACTIVE_ORG_ID)
    request.session[SessionOrgMiddleware.SESSION_ACTIVE_ORG_ID] = org_id
    if previous_org_id != org_id:
        logger.info(
            "active_org_id_changed",
            user_id=str(getattr(request.user, "id", "")) if getattr(request, "user", None) else "",
            previous_org_id=str(previous_org_id) if previous_org_id else "",
            org_id=str(org_id),
            source=source,
        )
