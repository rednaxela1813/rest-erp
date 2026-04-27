# rest-erp/apps/payments/providers/nexo.py
from __future__ import annotations

import structlog

from apps.payments.nexo import NexoClient
from apps.payments.providers.base import BasePaymentProvider

logger = structlog.get_logger(__name__)

_NEXO_SUCCESS = "Success"


def _result(response: dict) -> str:
    """Extract Result from any SaleToPOIResponse."""
    poi = response.get("SaleToPOIResponse", {})
    for key in ("PaymentResponse", "ReversalResponse", "DiagnosisResponse", "TransactionStatusResponse"):
        block = poi.get(key)
        if block:
            return block.get("Response", {}).get("Result", "")
    return ""


def _poi_transaction_id(response: dict) -> str | None:
    poi = response.get("SaleToPOIResponse", {})
    return poi.get("PaymentResponse", {}).get("POIData", {}).get("POITransactionID", {}).get("TransactionID")


def _build_client(payment) -> NexoClient:
    terminal = payment.terminal
    if not terminal or not terminal.host:
        raise RuntimeError(f"Terminal for payment {payment.public_id} has no host configured.")
    return NexoClient(
        host=terminal.host,
        port=terminal.port,
        sale_id=str(payment.org.public_id),
        poi_id=terminal.code or terminal.name,
    )


class NexoProvider(BasePaymentProvider):
    """
    Card-payment provider via NEXO 3.1 (SUNMI P3H / Besteron).

    Flow: authorize (sends payment to terminal) → capture (polls result).
    Refund: reverse the captured transaction on the terminal.
    """

    def authorize(self, *, payment, timeout_s: int) -> dict:
        client = _build_client(payment)
        logger.info(
            "nexo_authorize_started",
            payment_id=str(payment.public_id),
            host=payment.terminal.host,
            amount=str(payment.amount),
        )
        response = client.payment(amount=payment.amount, currency=payment.currency)
        result = _result(response)
        if result != _NEXO_SUCCESS:
            error_condition = (
                response.get("SaleToPOIResponse", {})
                .get("PaymentResponse", {})
                .get("Response", {})
                .get("ErrorCondition", "unknown")
            )
            logger.warning(
                "nexo_authorize_failed",
                payment_id=str(payment.public_id),
                result=result,
                error_condition=error_condition,
            )
            raise RuntimeError(f"NEXO authorize failed: {error_condition}")

        logger.info("nexo_authorize_succeeded", payment_id=str(payment.public_id))
        return response

    def capture(self, *, payment, timeout_s: int) -> dict:
        """
        For synchronous NEXO the terminal already authorized+captured in one shot.
        We treat capture as a status confirmation of the stored authorize response.
        """
        raw = payment.raw_provider_payload or {}
        result = _result(raw)
        if result != _NEXO_SUCCESS:
            raise RuntimeError("Cannot capture: underlying NEXO authorize was not successful.")
        logger.info("nexo_capture_confirmed", payment_id=str(payment.public_id))
        return {"ok": True, "provider": "nexo", "action": "capture"}

    def refund(self, *, payment, timeout_s: int) -> dict:
        """
        Attempt a full reversal via NEXO. Falls back to a refund transaction
        if the POI transaction ID is not stored (e.g. payment too old).
        """
        client = _build_client(payment)
        poi_tx_id = _poi_transaction_id(payment.raw_provider_payload or {})

        if poi_tx_id:
            logger.info(
                "nexo_reversal_started",
                payment_id=str(payment.public_id),
                poi_tx_id=poi_tx_id,
            )
            response = client.reversal(poi_transaction_id=poi_tx_id)
        else:
            logger.info(
                "nexo_refund_started",
                payment_id=str(payment.public_id),
                amount=str(payment.amount),
            )
            response = client.refund(amount=payment.amount, currency=payment.currency)

        result = _result(response)
        if result != _NEXO_SUCCESS:
            error_condition = (
                response.get("SaleToPOIResponse", {})
                .get("ReversalResponse", {})
                .get("Response", {})
                .get("ErrorCondition", "unknown")
            )
            logger.warning(
                "nexo_refund_failed",
                payment_id=str(payment.public_id),
                result=result,
                error_condition=error_condition,
            )
            raise RuntimeError(f"NEXO refund failed: {error_condition}")

        logger.info("nexo_refund_succeeded", payment_id=str(payment.public_id))
        return response

    def capture_status(self, *, payment, timeout_s: int) -> dict:
        """
        Reconciliation: ask the terminal for the status of the last transaction.
        """
        raw = payment.raw_provider_payload or {}
        result = _result(raw)
        if result == _NEXO_SUCCESS:
            return {"status": "confirmed"}
        if payment.status == payment.Status.FAILED:
            return {"status": "failed"}
        return {"status": "pending"}
