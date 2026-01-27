from django.urls import path

from apps.payments.api_views import PaymentCaptureApi, PaymentStartApi

urlpatterns = [
    path("payments/start/", PaymentStartApi.as_view(), name="payments-start"),
    path("payments/<uuid:public_id>/capture/", PaymentCaptureApi.as_view(), name="payments-capture"),
]
