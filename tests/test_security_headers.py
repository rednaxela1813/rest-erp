from django.http import HttpResponse
from django.test import override_settings

from config.security import BrowserSecurityHeadersMiddleware


@override_settings(
    CORS_ALLOWED_ORIGINS=["https://frontend.example.com"],
    CORS_ALLOW_CREDENTIALS=True,
    CSP_REPORT_ONLY=False,
)
def test_security_middleware_sets_cors_and_csp_headers(rf):
    middleware = BrowserSecurityHeadersMiddleware(lambda request: HttpResponse("ok"))
    request = rf.get("/", HTTP_ORIGIN="https://frontend.example.com")

    response = middleware(request)

    assert response["Access-Control-Allow-Origin"] == "https://frontend.example.com"
    assert response["Access-Control-Allow-Credentials"] == "true"
    assert "Content-Security-Policy" in response
    assert "default-src 'self'" in response["Content-Security-Policy"]


@override_settings(
    CORS_ALLOWED_ORIGINS=["https://frontend.example.com"],
    CORS_ALLOW_CREDENTIALS=True,
    CSP_REPORT_ONLY=True,
)
def test_security_middleware_uses_report_only_header_when_enabled(rf):
    middleware = BrowserSecurityHeadersMiddleware(lambda request: HttpResponse("ok"))
    request = rf.get("/")

    response = middleware(request)

    assert "Content-Security-Policy-Report-Only" in response
