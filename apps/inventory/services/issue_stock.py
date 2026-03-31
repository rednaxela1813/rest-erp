from decimal import Decimal

from django.db import transaction

from apps.inventory.models import StockLot, StockMovement
from apps.inventory.exceptions import LotNotFound, LotNotAvailable, InsufficientStock


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
    with transaction.atomic():
        try:
            lot = (
                StockLot.objects
                .select_for_update()
                .get(org=org, label_code=label_code)
            )
        except StockLot.DoesNotExist:
            raise LotNotFound(
                f"Партия с label_code='{label_code}' не найдена."
            )

        if lot.status != StockLot.Status.ACTIVE:
            raise LotNotAvailable(
                f"Партия '{label_code}' недоступна для списания: статус '{lot.status}'."
            )

        if quantity > lot.remaining_qty:
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

    return lot, movement