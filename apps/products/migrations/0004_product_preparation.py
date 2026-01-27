from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0003_product_bundles"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="requires_preparation",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="product",
            name="stock_qty",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True),
        ),
    ]
