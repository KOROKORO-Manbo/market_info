from django.db import models


class MarketSnapshot(models.Model):
    STATUS_OK = "ok"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_OK, "OK"),
        (STATUS_ERROR, "Error"),
    ]

    report_date = models.DateField(db_index=True)
    fetched_at_jst = models.DateTimeField()
    source_name = models.CharField(max_length=100)
    source_url = models.URLField(max_length=500, blank=True)
    value = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    change_vs_prev_bd = models.FloatField(null=True, blank=True)
    change_vs_prev_bd_pct = models.FloatField(null=True, blank=True)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OK)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-report_date", "source_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["report_date", "source_name"],
                name="unique_snapshot_per_source_per_day",
            )
        ]

    def __str__(self):
        return f"{self.report_date} | {self.source_name} | {self.value} {self.unit}"
