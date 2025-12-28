# project/backend/apps/products/serializers.py
from rest_framework import serializers
from config.orgs.org_context import get_request_org

from .models import Unit, TaxRate


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ["public_id", "name"]
        read_only_fields = ["public_id"]

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")

        request = self.context.get("request")
        if request is None:
            return value

        org = get_request_org(request)

        # При создании: не допускаем активный дубль имени в org
        # При обновлении (позже): исключим self.instance
        qs = Unit.objects.filter(org=org, status=Unit.STATUS_ACTIVE, name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError("Unit with this name already exists.")

        return value



class TaxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRate
        fields = ["public_id", "name", "rate"]
        read_only_fields = ["public_id"]
