from django.urls import path

from apps.payments.api_views import (
    DeviceCommandAckApi,
    DeviceCommandPullApi,
    PaymentCaptureApi,
    PaymentManualResolutionApi,
    PaymentStartApi,
    PaymentStatusApi,
    FiscalReceiptsHealthApi,
    ShiftCloseApi,
    ShiftOpenApi,
    ShiftReportApi,
)

urlpatterns = [
    path("payments/start/", PaymentStartApi.as_view(), name="payments-start"),
    path("payments/<uuid:public_id>/capture/", PaymentCaptureApi.as_view(), name="payments-capture"),
    path("payments/<uuid:public_id>/status/", PaymentStatusApi.as_view(), name="payments-status"),
    path(
        "payments/<uuid:public_id>/manual-resolution/",
        PaymentManualResolutionApi.as_view(),
        name="payments-manual-resolution",
    ),
    path("health/fiscal-receipts/", FiscalReceiptsHealthApi.as_view(), name="health-fiscal-receipts"),
    path("device/commands/pull/", DeviceCommandPullApi.as_view(), name="device-commands-pull"),
    path("device/commands/<uuid:public_id>/ack/", DeviceCommandAckApi.as_view(), name="device-commands-ack"),
    path("shifts/open/", ShiftOpenApi.as_view(), name="shifts-open"),
    path("shifts/<uuid:public_id>/close/", ShiftCloseApi.as_view(), name="shifts-close"),
    path("shifts/<uuid:public_id>/report/", ShiftReportApi.as_view(), name="shifts-report"),
]
