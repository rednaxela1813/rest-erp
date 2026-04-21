from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Inventory"

    def ready(self) -> None:
        from apps.inventory.order_handlers import handle_order_cancelled_restore_stock
        from apps.orders.signals import order_cancelled

        order_cancelled.connect(
            handle_order_cancelled_restore_stock,
            dispatch_uid="inventory.handle_order_cancelled_restore_stock",
        )
