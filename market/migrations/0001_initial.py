import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MarketSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("report_date", models.DateField(db_index=True)),
                ("fetched_at_jst", models.DateTimeField()),
                ("source_name", models.CharField(max_length=100)),
                ("source_url", models.URLField(blank=True, max_length=500)),
                ("value", models.FloatField(blank=True, null=True)),
                ("unit", models.CharField(blank=True, max_length=50)),
                ("change_vs_prev_bd", models.FloatField(blank=True, null=True)),
                ("change_vs_prev_bd_pct", models.FloatField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("status", models.CharField(
                    choices=[("ok", "OK"), ("error", "Error")],
                    default="ok",
                    max_length=20,
                )),
                ("error_message", models.TextField(blank=True)),
            ],
            options={
                "ordering": ["-report_date", "source_name"],
            },
        ),
        migrations.AddConstraint(
            model_name="marketsnapshot",
            constraint=models.UniqueConstraint(
                fields=["report_date", "source_name"],
                name="unique_snapshot_per_source_per_day",
            ),
        ),
    ]
