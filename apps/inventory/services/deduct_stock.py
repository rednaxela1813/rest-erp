from decimal import Decimal

from django.db import transaction

from apps.inventory.exceptions import InsufficientStock
from apps.inventory.models import StockLot, StockMovement
from apps.accounting.logic.record_stock_out import record_stock_out


def deduct_stock(
    *,
    org,
    product,
    quantity: Decimal,
    reason: str = "order_paid",
    comment: str = "",
) -> list[StockMovement]:
    """
    Автоматическое списание при оплате заказа.

    Берёт активные партии по FIFO (received_at), блокирует их,
    списывает нужное количество, создаёт StockMovement(OUT) для каждой
    затронутой партии.

    Бросает InsufficientStock если суммарного остатка недостаточно.
    """
    with transaction.atomic():
        lots = (
            StockLot.objects
            .select_for_update()
            .filter(org=org, product=product, status=StockLot.Status.ACTIVE)
            .order_by("received_at", "id")
        )

        total_available = sum(lot.remaining_qty for lot in lots)
        if total_available < quantity:
            raise InsufficientStock(
                f"Недостаточно остатка для '{product}': "
                f"запрошено {quantity}, доступно {total_available}."
            )

        movements = []
        remaining_to_deduct = quantity

        for lot in lots:
            if remaining_to_deduct <= 0:
                break

            deduct_from_lot = min(lot.remaining_qty, remaining_to_deduct)
            lot.remaining_qty -= deduct_from_lot
            remaining_to_deduct -= deduct_from_lot

            if lot.remaining_qty == 0:
                lot.status = StockLot.Status.DEPLETED

            lot.save(update_fields=["remaining_qty", "status", "updated_at"])

            movement = StockMovement.objects.create(
                org=org,
                product=product,
                lot=lot,
                movement_type=StockMovement.MovementType.OUT,
                quantity=deduct_from_lot,
                unit_cost_snapshot=lot.unit_cost,
                reason=reason,
                comment=comment,
            )
            movements.append(movement)
            record_stock_out(movement=movement)

       

    return movements


def restore_stock(
    *,
    org,
    product,
    quantity: Decimal,
    reason: str = "order_cancelled",
    comment: str = "",
) -> None:
    """
    Возврат остатка при отмене заказа.

    Партионный возврат (в какую партию вернуть?) пока не реализован.
    """
    with transaction.atomic():
        return None
