from decimal import Decimal

from django.db import OperationalError
from django.db import transaction
import structlog

from apps.inventory.exceptions import InsufficientStock
from apps.inventory.models import StockLot, StockMovement
from apps.accounting.logic.record_stock_out import record_stock_out

logger = structlog.get_logger(__name__)


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
    logger.info(
        "stock_deduct_started",
        org_id=str(org.public_id),
        product_id=str(product.public_id),
        product_name=product.name,
        quantity=str(quantity),
        reason=reason,
    )
    try:
        with transaction.atomic():
            lots = (
                StockLot.objects.select_for_update()
                .filter(org=org, product=product, status=StockLot.Status.ACTIVE)
                .order_by("received_at", "id")
            )

            total_available = sum(lot.remaining_qty for lot in lots)
            if total_available < quantity:
                logger.warning(
                    "stock_deduct_insufficient",
                    org_id=str(org.public_id),
                    product_id=str(product.public_id),
                    product_name=product.name,
                    requested_qty=str(quantity),
                    total_available=str(total_available),
                    reason=reason,
                )
                raise InsufficientStock(
                    f"Недостаточно остатка для '{product}': запрошено {quantity}, доступно {total_available}."
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
    except OperationalError as exc:
        if "database table is locked" not in str(exc).lower():
            raise
        logger.warning(
            "stock_deduct_locked",
            org_id=str(org.public_id),
            product_id=str(product.public_id),
            product_name=product.name,
            quantity=str(quantity),
            reason=reason,
        )
        raise InsufficientStock(f"Недостаточно остатка для '{product}': запрошено {quantity}, доступно 0.") from exc

    logger.info(
        "stock_deduct_succeeded",
        org_id=str(org.public_id),
        product_id=str(product.public_id),
        product_name=product.name,
        requested_qty=str(quantity),
        movements_count=len(movements),
        deducted_qty=str(sum((m.quantity for m in movements), Decimal("0.000"))),
        reason=reason,
    )
    return movements


def restore_stock(
    *,
    org,
    product,
    quantity: Decimal,
    reason: str = "order_cancelled",
    comment: str = "",
) -> StockMovement:
    """
    Возврат товара на склад при отмене заказа.

    Стратегия: возвращаем в последнюю по FIFO партию (ту что списывалась
    последней). Если партия была DEPLETED — реактивируем её в ACTIVE.
    Создаёт StockMovement(IN) для аудита.

    Не поддерживает возврат большего количества чем было в партии —
    remaining_qty не может превысить initial_qty (CHECK constraint в БД).
    """
    logger.info(
        "stock_restore_started",
        org_id=str(org.public_id),
        product_id=str(product.public_id),
        product_name=product.name,
        quantity=str(quantity),
        reason=reason,
    )
    with transaction.atomic():
        # Берём последнюю партию в обратном FIFO-порядке (последней списывалась первой)
        # Включаем DEPLETED — возврат должен реактивировать опустошённую партию
        lot = (
            StockLot.objects.select_for_update()
            .filter(
                org=org,
                product=product,
                status__in=[
                    StockLot.Status.ACTIVE,
                    StockLot.Status.DEPLETED,
                ],
            )
            .order_by("-received_at", "-id")
            .first()
        )

        if lot is None:
            logger.warning(
                "stock_restore_no_lot",
                org_id=str(org.public_id),
                product_id=str(product.public_id),
                product_name=product.name,
                quantity=str(quantity),
                reason=reason,
            )
            raise ValueError(f"Нет партии для возврата товара '{product}'. Невозможно восстановить {quantity} единиц.")

        lot.remaining_qty += quantity
        lot.status = StockLot.Status.ACTIVE
        lot.save(update_fields=["remaining_qty", "status", "updated_at"])

        movement = StockMovement.objects.create(
            org=org,
            product=product,
            lot=lot,
            movement_type=StockMovement.MovementType.IN,
            quantity=quantity,
            unit_cost_snapshot=lot.unit_cost,
            reason=reason,
            comment=comment,
        )

    logger.info(
        "stock_restore_succeeded",
        org_id=str(org.public_id),
        product_id=str(product.public_id),
        product_name=product.name,
        quantity=str(quantity),
        lot_id=str(lot.id),
        reason=reason,
    )
    return movement
