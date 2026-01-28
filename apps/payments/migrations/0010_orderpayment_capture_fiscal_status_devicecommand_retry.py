from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0009_alter_devicecommand_command_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderpayment",
            name="capture_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "Pending"),
                    ("timeout", "Timeout"),
                    ("confirmed", "Confirmed"),
                ],
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="orderpayment",
            name="fiscal_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "Pending"),
                    ("failed", "Failed"),
                    ("confirmed", "Confirmed"),
                ],
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="devicecommand",
            name="next_attempt_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
