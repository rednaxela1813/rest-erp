from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


class BrowserSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        self._apply_cors_headers(request, response)
        self._apply_csp_header(response)
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response

    def _apply_cors_headers(self, request, response) -> None:
        origin = request.headers.get("Origin")
        if not origin or origin not in settings.CORS_ALLOWED_ORIGINS:
            return

        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-ORG-ID"
        patch_vary_headers(response, ["Origin"])
        if settings.CORS_ALLOW_CREDENTIALS:
            response["Access-Control-Allow-Credentials"] = "true"

    def _apply_csp_header(self, response) -> None:
        header_name = "Content-Security-Policy-Report-Only" if settings.CSP_REPORT_ONLY else "Content-Security-Policy"
        response[header_name] = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "script-src 'self' 'unsafe-inline' https:; "
            "font-src 'self' data: https:; "
            "connect-src 'self' https:; "
            "object-src 'none'"
        )
