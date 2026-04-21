from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0002_product_product_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="image_url",
            field=models.URLField(blank=True, default=""),
        ),
    ]
