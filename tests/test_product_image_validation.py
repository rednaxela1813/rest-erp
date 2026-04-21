from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.products.models import Product, TaxRate, Unit, product_image_upload_to


pytestmark = pytest.mark.django_db


def test_product_image_upload_path_coerces_unknown_suffix_to_bin(org_factory):
    org = org_factory()
    product = Product(org=org, name="Burger")

    path = product_image_upload_to(product, "burger.exe")

    assert path.startswith(f"products/{org.id}/")
    assert path.endswith(".bin")


def test_product_clean_rejects_oversized_image(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product(
        org=org,
        name="Burger",
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )
    product.image = SimpleUploadedFile(
        "burger.png",
        b"0" * (5 * 1024 * 1024 + 1),
        content_type="image/png",
    )

    with pytest.raises(ValidationError) as exc:
        product.clean()

    assert "image" in exc.value.message_dict


def test_product_clean_rejects_unsupported_image_content_type(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product(
        org=org,
        name="Burger",
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )
    product.image = SimpleUploadedFile(
        "burger.svg",
        b"<svg></svg>",
        content_type="image/svg+xml",
    )

    with pytest.raises(ValidationError) as exc:
        product.clean()

    assert "image" in exc.value.message_dict
