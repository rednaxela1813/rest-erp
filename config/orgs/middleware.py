from django.utils.deprecation import MiddlewareMixin


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
