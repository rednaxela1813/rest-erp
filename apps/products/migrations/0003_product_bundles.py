from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0002_product_pricing_barcode"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="is_bundle",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="product",
            name="bundle_discount_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=5,
                validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
            ),
        ),
        migrations.CreateModel(
            name="BundleItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("qty", models.DecimalField(decimal_places=3, default=Decimal("1.000"), max_digits=12)),
                (
                    "bundle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bundle_items",
                        to="products.product",
                    ),
                ),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bundle_components",
                        to="products.product",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("bundle", "component"),
                        name="uniq_bundle_component",
                    ),
                ],
            },
        ),
    ]
