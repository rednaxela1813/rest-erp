class InventoryError(Exception):
    """Базовый класс для всех бизнес-ошибок инвентаризации."""


class LotNotFound(InventoryError):
    """Партия с таким label_code не найдена."""


class LotNotAvailable(InventoryError):
    """Партия существует, но не в статусе active (depleted, archived)."""


class InsufficientStock(InventoryError):
    """Запрошено больше, чем есть в партии."""
