from __future__ import annotations

from apps.accounting.logic.record_stock_return import record_stock_return


def handle_order_cancelled_record_accounting(*, order, **kwargs) -> None:
    for movement in getattr(order, "_restored_stock_movements", []):
        record_stock_return(movement=movement)
