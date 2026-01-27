from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal
import uuid


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CashDrawerMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("movement_type", models.CharField(choices=[("opening_float", "Opening float"), ("cash_in", "Cash in"), ("cash_out", "Cash out"), ("sale_cash", "Cash sale")], max_length=32)),
                ("amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("reason", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cash_drawer_movements", to=settings.AUTH_USER_MODEL)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cash_movements", to="payments.cashiersession")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="cashdrawermovement",
            index=models.Index(fields=["session", "created_at"], name="payments_ca_session_5f0b3b_idx"),
        ),
    ]
