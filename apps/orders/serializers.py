# apps/orders/serializers.py

from rest_framework import serializers

from config.orgs.org_context import get_request_org
from apps.products.models import Product, ProductAddon, ProductVariant, Unit, TaxRate

from .models import KitchenTicket, Order, OrderItem, OrderItemAddon, OrderStatusEvent
from .logic.status_fsm import assert_can_transition


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ["public_id", "status"]
        read_only_fields = ["public_id"]

    def validate_status(self, value):
        """
        API-контракт для статуса:
        - Запрещаем любые переходы, кроме разрешённых FSM.
        - Доп. правило: draft -> paid только если есть items.

        ВАЖНО:
        - Повторные команды (paid->paid / cancelled->cancelled) мы НЕ запрещаем здесь,
          потому что бизнес-ошибки и тексты сообщений живут в use-case'ах.
          Но тесты у тебя требуют 400 на повтор — это обеспечивается в pay_order/cancel_*.
        """
        # create: обычно статус дефолтится в модели; если всё же передали — не ломаем
        if not self.instance:
            return value

        current = self.instance.status
        new = value

        # Если клиент шлёт тот же статус — пропускаем на уровень view/use-case.
        # Там решится: либо idempotent, либо ValidationError.
        if new == current:
            return value

        # 1) FSM: единая таблица переходов
        assert_can_transition(current=current, new=new)

        # 2) Доп. правило: draft -> paid только если есть items
        if current == Order.STATUS_DRAFT and new == Order.STATUS_PAID:
            if not self.instance.items.exists():
                raise serializers.ValidationError("Cannot set paid order without items.")

        return value


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["public_id", "product_name"]
        read_only_fields = ["public_id", "product_name"]


class OrderItemCreateSerializer(serializers.ModelSerializer):
    # принимаем public_id, а не pk
    product = serializers.UUIDField()
    unit = serializers.UUIDField()
    tax_rate = serializers.UUIDField()
    variant = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    addons = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        write_only=True,
    )
    note = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = OrderItem
        fields = [
            "public_id",
            "product",
            "product_name",
            "qty",
            "unit",
            "unit_price",
            "tax_rate",
            "variant",
            "addons",
            "note",
        ]
        read_only_fields = ["public_id", "product_name"]

    def validate(self, attrs):
        """
        Валидируем, что связанные сущности существуют, активны и принадлежат org из X-ORG-ID.
        """
        request = self.context["request"]
        org = get_request_org(request)

        try:
            product_obj = Product.objects.get(
                org=org,
                public_id=attrs["product"],
                status=Product.STATUS_ACTIVE,
            )
        except Product.DoesNotExist:
            raise serializers.ValidationError({"product": "Invalid product."})

        try:
            unit_obj = Unit.objects.get(
                org=org,
                public_id=attrs["unit"],
                status=Unit.STATUS_ACTIVE,
            )
        except Unit.DoesNotExist:
            raise serializers.ValidationError({"unit": "Invalid unit."})

        try:
            tax_obj = TaxRate.objects.get(
                org=org,
                public_id=attrs["tax_rate"],
                status=TaxRate.STATUS_ACTIVE,
            )
        except TaxRate.DoesNotExist:
            raise serializers.ValidationError({"tax_rate": "Invalid tax_rate."})

        attrs["product_obj"] = product_obj
        attrs["unit_obj"] = unit_obj
        attrs["tax_obj"] = tax_obj

        variant_public_id = attrs.get("variant")
        if variant_public_id:
            try:
                variant_obj = product_obj.variants.get(
                    public_id=variant_public_id,
                    status=ProductVariant.STATUS_ACTIVE,
                )
            except ProductVariant.DoesNotExist:
                raise serializers.ValidationError({"variant": "Invalid variant."})
            attrs["variant_obj"] = variant_obj

        addon_public_ids = attrs.get("addons") or []
        addon_objs = list(
            ProductAddon.objects.filter(
                product=product_obj,
                public_id__in=addon_public_ids,
                status=ProductAddon.STATUS_ACTIVE,
            )
        )
        if len(addon_objs) != len(addon_public_ids):
            raise serializers.ValidationError({"addons": "Invalid addons."})
        attrs["addon_objs"] = addon_objs
        return attrs

    def create(self, validated_data):
        """
        Создаём OrderItem:
        - заменяем UUID-идентификаторы на FK объекты
        - записываем snapshot product_name
        """
        product_obj = validated_data.pop("product_obj")
        unit_obj = validated_data.pop("unit_obj")
        tax_obj = validated_data.pop("tax_obj")
        variant_obj = validated_data.pop("variant_obj", None)
        addon_objs = validated_data.pop("addon_objs", [])

        validated_data.pop("product", None)
        validated_data.pop("unit", None)
        validated_data.pop("tax_rate", None)
        validated_data.pop("variant", None)
        validated_data.pop("addons", None)

        validated_data["product_name"] = product_obj.name
        validated_data["variant_name"] = variant_obj.name if variant_obj else ""

        item = OrderItem.objects.create(
            product=product_obj,
            unit=unit_obj,
            tax_rate=tax_obj,
            variant=variant_obj,
            **validated_data,
        )

        if addon_objs:
            OrderItemAddon.objects.bulk_create(
                [
                    OrderItemAddon(
                        order_item=item,
                        addon=addon,
                        name=addon.name,
                        price=addon.price,
                        qty=item.qty,
                    )
                    for addon in addon_objs
                ]
            )
        return item


class OrderStatusEventSerializer(serializers.ModelSerializer):
    order = serializers.UUIDField(source="order.public_id", read_only=True)
    actor = serializers.UUIDField(source="actor.public_id", read_only=True, allow_null=True)

    class Meta:
        model = OrderStatusEvent
        fields = [
            "public_id",
            "order",
            "actor",
            "from_status",
            "to_status",
            "reason",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class KitchenTicketSerializer(serializers.ModelSerializer):
    order = serializers.UUIDField(source="order.public_id", read_only=True)
    product = serializers.UUIDField(source="product.public_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = KitchenTicket
        fields = ["public_id", "order", "product", "product_name", "qty", "status", "created_at"]
        read_only_fields = fields


class KitchenTicketUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = KitchenTicket
        fields = ["status"]

    def validate_status(self, value: str) -> str:
        allowed = {
            KitchenTicket.Status.IN_PROGRESS,
            KitchenTicket.Status.DONE,
            KitchenTicket.Status.CANCELLED,
        }
        if value not in allowed:
            raise serializers.ValidationError("Invalid status.")
        return value
