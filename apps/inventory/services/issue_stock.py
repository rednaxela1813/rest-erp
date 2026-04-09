from decimal import Decimal

from django.db import transaction
import structlog

from apps.inventory.models import StockLot, StockMovement
from apps.inventory.exceptions import LotNotFound, LotNotAvailable, InsufficientStock

logger = structlog.get_logger(__name__)


def issue_by_scanned_lot(
    *,
    org,
    label_code: str,
    quantity: Decimal,
    reason: str = "",
    comment: str = "",
) -> tuple[StockLot, StockMovement]:
    """
    Списание товара по отсканированной этикетке партии.

    Находит партию по label_code, блокирует строку,
    проверяет возможность списания, уменьшает остаток,
    создаёт StockMovement(OUT).
    Возвращает (lot, movement).
    """
    logger.info(
        "stock_issue_scanned_started",
        org_id=str(org.public_id),
        label_code=label_code,
        quantity=str(quantity),
        reason=reason,
    )
    with transaction.atomic():
        try:
            lot = (
                StockLot.objects
                .select_for_update()
                .get(org=org, label_code=label_code)
            )
        except StockLot.DoesNotExist:
            logger.warning(
                "stock_issue_scanned_lot_not_found",
                org_id=str(org.public_id),
                label_code=label_code,
                quantity=str(quantity),
            )
            raise LotNotFound(
                f"Партия с label_code='{label_code}' не найдена."
            )

        if lot.status != StockLot.Status.ACTIVE:
            logger.warning(
                "stock_issue_scanned_lot_not_available",
                org_id=str(org.public_id),
                label_code=label_code,
                lot_status=lot.status,
                quantity=str(quantity),
            )
            raise LotNotAvailable(
                f"Партия '{label_code}' недоступна для списания: статус '{lot.status}'."
            )

        if quantity > lot.remaining_qty:
            logger.warning(
                "stock_issue_scanned_insufficient",
                org_id=str(org.public_id),
                label_code=label_code,
                requested_qty=str(quantity),
                remaining_qty=str(lot.remaining_qty),
            )
            raise InsufficientStock(
                f"Запрошено {quantity}, остаток в партии '{label_code}': {lot.remaining_qty}."
            )

        lot.remaining_qty -= quantity

        if lot.remaining_qty == 0:
            lot.status = StockLot.Status.DEPLETED

        lot.save(update_fields=["remaining_qty", "status", "updated_at"])

        movement = StockMovement.objects.create(
            org=org,
            product=lot.product,
            lot=lot,
            movement_type=StockMovement.MovementType.OUT,
            quantity=quantity,
            unit_cost_snapshot=lot.unit_cost,
            reason=reason,
            comment=comment,
        )

    logger.info(
        "stock_issue_scanned_succeeded",
        org_id=str(org.public_id),
        product_id=str(lot.product.public_id),
        product_name=lot.product.name,
        label_code=label_code,
        issued_qty=str(quantity),
        remaining_qty=str(lot.remaining_qty),
        movement_id=str(movement.id),
    )
    return lot, movement
