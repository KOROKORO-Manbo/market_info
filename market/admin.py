from django.contrib import admin
from .models import MarketSnapshot


@admin.register(MarketSnapshot)
class MarketSnapshotAdmin(admin.ModelAdmin):
    list_display = ("report_date", "source_name", "value", "unit", "change_vs_prev_bd", "change_vs_prev_bd_pct", "status")
    list_filter = ("status", "report_date", "source_name")
    search_fields = ("source_name",)
    ordering = ("-report_date", "source_name")
