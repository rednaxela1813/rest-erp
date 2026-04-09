# backend/apps/inventory/services/receive_stock.py
from decimal import Decimal
from datetime import datetime

from django.db import transaction
from django.utils import timezone
import structlog

from apps.inventory.models import StockLot, StockMovement
from apps.accounting.logic.record_stock_receipt import record_stock_receipt

logger = structlog.get_logger(__name__)


def receive_stock(
    *,
    org,
    product,
    initial_qty: Decimal,
    unit_cost: Decimal,
    label_code: str = "",
    batch_number: str = "",
    supplier=None,
    storage_location=None,
    expires_at: datetime | None = None,
    received_at: datetime | None = None,
    comment: str = "",
) -> tuple[StockLot, StockMovement]:
    """
    Оприходование партии товара.

    Создаёт StockLot и StockMovement(IN) в одной транзакции.
    Возвращает (lot, movement).
    """
    logger.info(
        "stock_receive_started",
        org_id=str(org.public_id),
        product_id=str(product.public_id),
        product_name=product.name,
        initial_qty=str(initial_qty),
        unit_cost=str(unit_cost),
        label_code=label_code,
    )
    with transaction.atomic():
        lot = StockLot.objects.create(
            org=org,
            product=product,
            supplier=supplier,
            storage_location=storage_location,
            label_code=label_code,
            batch_number=batch_number,
            initial_qty=initial_qty,
            remaining_qty=initial_qty,
            unit_cost=unit_cost,
            expires_at=expires_at,
            received_at=received_at or timezone.now(),
            status=StockLot.Status.ACTIVE,
            
            
        )

       

        movement = StockMovement.objects.create(
            org=org,
            product=product,
            lot=lot,
            movement_type=StockMovement.MovementType.IN,
            quantity=initial_qty,
            unit_cost_snapshot=unit_cost,
            comment=comment,
        )
        
        record_stock_receipt(lot=lot)  # связать с функцией, которая создаёт запись в бухгалтерии

    logger.info(
        "stock_receive_succeeded",
        org_id=str(org.public_id),
        product_id=str(product.public_id),
        product_name=product.name,
        lot_id=str(lot.id),
        movement_id=str(movement.id),
        received_qty=str(initial_qty),
        remaining_qty=str(lot.remaining_qty),
        label_code=lot.label_code,
    )
    return lot, movement
