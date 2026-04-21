from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"

    def ready(self) -> None:
        from apps.accounting.order_handlers import handle_order_cancelled_record_accounting
        from apps.orders.signals import order_cancelled

        order_cancelled.connect(
            handle_order_cancelled_record_accounting,
            dispatch_uid="accounting.handle_order_cancelled_record_accounting",
        )
