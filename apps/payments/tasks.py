from __future__ import annotations

import structlog
from celery import shared_task
from django.conf import settings

from config.orgs.models import Organization

from apps.payments.logic.dispatch_commands import dispatch_pending_device_commands
from apps.payments.logic.ekasa_commands import process_ekasa_device_commands
from apps.payments.logic.mock_commands import process_mock_device_commands
from apps.payments.logic.reconciliation import (
    reconcile_capture_status,
    reconcile_fiscal_status,
    reconcile_fiscal_status_for_all_orgs,
)
from apps.payments.streaming import publish_device_commands
from apps.payments.providers import registry
from apps.payments.ekasa.client import EkasaClient

logger = structlog.get_logger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def dispatch_device_commands(self, org_id: int, limit: int = 50) -> dict:
    """
    Pull pending device commands and stream them via Redis.

    This task is intentionally small and idempotent:
    - Pull locks rows and marks them as SENT.
    - Publishing to Redis is safe because command idempotency keys are stable.
    """
    return dispatch_pending_device_commands(
        org_id=org_id,
        limit=limit,
        ekasa_enabled=getattr(settings, "EKASA_ENABLED", False),
        publisher=publish_device_commands,
        logger=logger,
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_mock(self, org_id: int, limit: int = 50) -> dict:
    """
    Mock Local Agent:
    - Pulls pending device commands
    - Validates payload shape
    - ACKs success or FAILs with error
    - Can simulate offline fiscalization via FISCAL_MOCK_OFFLINE
    """
    return process_mock_device_commands(
        org_id=org_id,
        limit=limit,
        fiscal_mock_offline=getattr(settings, "FISCAL_MOCK_OFFLINE", False),
        logger=logger,
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def dispatch_device_commands_for_all_orgs(self, limit: int = 50) -> dict:
    """
    Periodic task to stream pending device commands for every org.

    This keeps offline fiscal receipts moving without manual triggers.
    """
    logger.info("task_dispatch_device_commands_for_all_orgs_started", limit=limit)
    results = []
    for org_id in Organization.objects.values_list("id", flat=True):
        results.append(dispatch_device_commands.delay(org_id=org_id, limit=limit))

    result = {
        "orgs_processed": len(results),
        "results": results,
    }
    logger.info(
        "task_dispatch_device_commands_for_all_orgs_succeeded",
        orgs_processed=result["orgs_processed"],
    )
    return result


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_mock_for_all_orgs(self, limit: int = 50) -> dict:
    """
    Periodic mock-agent task for all orgs.
    """
    logger.info("task_process_device_commands_mock_for_all_orgs_started", limit=limit)
    results = []
    for org_id in Organization.objects.values_list("id", flat=True):
        results.append(process_device_commands_mock.delay(org_id=org_id, limit=limit))

    result = {
        "orgs_processed": len(results),
        "results": results,
    }
    logger.info(
        "task_process_device_commands_mock_for_all_orgs_succeeded",
        orgs_processed=result["orgs_processed"],
    )
    return result


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_ekasa(self, org_id: int, limit: int = 50) -> dict:
    """
    eKasa Local Agent replacement:
    - Pulls fiscalize_* commands only
    - Registers receipt via eKasa Web API
    - ACKs or FAILs commands
    """
    return process_ekasa_device_commands(
        org_id=org_id,
        limit=limit,
        cash_register_code=settings.EKASA_CASH_REGISTER_CODE,
        client_factory=EkasaClient,
        logger=logger,
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_ekasa_for_all_orgs(self, limit: int = 50) -> dict:
    """
    Periodic eKasa agent task for all orgs.
    """
    logger.info("task_process_device_commands_ekasa_for_all_orgs_started", limit=limit)
    results = []
    for org_id in Organization.objects.values_list("id", flat=True):
        results.append(process_device_commands_ekasa.delay(org_id=org_id, limit=limit))

    result = {
        "orgs_processed": len(results),
        "results": results,
    }
    logger.info(
        "task_process_device_commands_ekasa_for_all_orgs_succeeded",
        orgs_processed=result["orgs_processed"],
    )
    return result


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reconcile_payment_capture(self, payment_id: int, timeout_s: int = 10) -> dict:
    """
    Reconcile capture status with the payment provider after outages.
    """
    return reconcile_capture_status(
        payment_id=payment_id,
        timeout_s=timeout_s,
        provider_registry=registry,
        logger=logger,
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reconcile_payment_fiscal_status(self, payment_id: int) -> dict:
    """
    Reconcile fiscalization status based on device command outcomes.
    """
    return reconcile_fiscal_status(payment_id=payment_id, logger=logger)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reconcile_payment_fiscal_status_for_all_orgs(self, limit: int = 200) -> dict:
    """
    Periodic reconciler for fiscal status.

    We only target payments that have fiscal commands stuck in PENDING/SENT/FAILED.
    """
    return reconcile_fiscal_status_for_all_orgs(
        limit=limit,
        reconcile_payment=reconcile_payment_fiscal_status,
        logger=logger,
    )
