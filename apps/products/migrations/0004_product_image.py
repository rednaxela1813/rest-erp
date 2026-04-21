from django.db import migrations, models

import apps.products.models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0003_product_image_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=apps.products.models.product_image_upload_to,
            ),
        ),
    ]
