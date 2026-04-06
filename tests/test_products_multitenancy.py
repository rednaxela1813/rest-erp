from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.products.admin import ProductAdminForm
from apps.products.models import Product, TaxRate, Unit


@pytest.mark.django_db
def test_product_clean_rejects_tax_rate_from_another_org(org_factory):
    org_a = org_factory(name="Org A")
    org_b = org_factory(name="Org B")
    unit = Unit.objects.create(org=org_a, name="pcs")
    foreign_tax_rate = TaxRate.objects.create(org=org_b, name="VAT 20", rate=Decimal("20.00"))
    product = Product(
        org=org_a,
        name="Burger",
        unit=unit,
        tax_rate=foreign_tax_rate,
        unit_price=Decimal("5.00"),
    )

    with pytest.raises(ValidationError) as exc:
        product.full_clean()

    assert "tax_rate" in exc.value.message_dict


@pytest.mark.django_db
def test_product_clean_rejects_unit_from_another_org(org_factory):
    org_a = org_factory(name="Org A")
    org_b = org_factory(name="Org B")
    foreign_unit = Unit.objects.create(org=org_b, name="pcs")
    tax_rate = TaxRate.objects.create(org=org_a, name="VAT 20", rate=Decimal("20.00"))
    product = Product(
        org=org_a,
        name="Burger",
        unit=foreign_unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )

    with pytest.raises(ValidationError) as exc:
        product.full_clean()

    assert "unit" in exc.value.message_dict


@pytest.mark.django_db
def test_product_admin_form_limits_unit_and_tax_rate_to_selected_org(org_factory):
    org_a = org_factory(name="Org A")
    org_b = org_factory(name="Org B")
    own_unit = Unit.objects.create(org=org_a, name="pcs")
    own_tax_rate = TaxRate.objects.create(org=org_a, name="VAT 20", rate=Decimal("20.00"))
    Unit.objects.create(org=org_b, name="kg")
    TaxRate.objects.create(org=org_b, name="VAT 10", rate=Decimal("10.00"))

    form = ProductAdminForm(data={"org": str(org_a.pk)})

    assert list(form.fields["unit"].queryset) == [own_unit]
    assert list(form.fields["tax_rate"].queryset) == [own_tax_rate]
