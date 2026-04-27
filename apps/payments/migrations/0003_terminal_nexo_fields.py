# rest-erp/apps/payments/migrations/0003_terminal_nexo_fields.py
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_alter_orderpayment_failure_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="terminal",
            name="host",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="terminal",
            name="port",
            field=models.PositiveIntegerField(default=7500),
        ),
    ]
