from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LogEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.CharField(max_length=16)),
                ("logger_name", models.CharField(blank=True, default="", max_length=128)),
                ("event", models.CharField(blank=True, default="", max_length=128)),
                ("message", models.TextField(blank=True, default="")),
                ("request_id", models.CharField(blank=True, default="", max_length=64)),
                ("org_id", models.CharField(blank=True, default="", max_length=64)),
                ("user_id", models.CharField(blank=True, default="", max_length=64)),
                ("path", models.CharField(blank=True, default="", max_length=255)),
                ("method", models.CharField(blank=True, default="", max_length=16)),
                ("task_id", models.CharField(blank=True, default="", max_length=64)),
                ("task_name", models.CharField(blank=True, default="", max_length=255)),
                ("raw", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="logentry",
            index=models.Index(fields=["org_id", "created_at"], name="logs_dash_org_id_8fd1b0_idx"),
        ),
        migrations.AddIndex(
            model_name="logentry",
            index=models.Index(fields=["level", "created_at"], name="logs_dash_level_2fe9f4_idx"),
        ),
        migrations.AddIndex(
            model_name="logentry",
            index=models.Index(fields=["request_id"], name="logs_dash_request_8b0c8f_idx"),
        ),
    ]
