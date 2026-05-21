"""
Fetch all market indicators and persist to MarketSnapshot.
Called from both the dashboard view (on-demand) and the management command.
"""
from . import services
from .models import MarketSnapshot


def refresh_all(report_date=None):
    if report_date is None:
        report_date = services.jst_now().date()
    prev_bd = services.previous_business_day(report_date)
    fetched_at = services.jst_now()

    prev_snaps = {
        s.source_name: s
        for s in MarketSnapshot.objects.filter(
            report_date=prev_bd, status=MarketSnapshot.STATUS_OK
        )
    }

    def _persist(rec):
        if (
            rec.get("change_vs_prev_bd") is None
            and rec.get("value") is not None
            and rec.get("status") != MarketSnapshot.STATUS_ERROR
        ):
            prev = prev_snaps.get(rec["source_name"])
            if prev and prev.value is not None:
                chg = rec["value"] - prev.value
                rec["change_vs_prev_bd"] = chg
                rec["change_vs_prev_bd_pct"] = chg / prev.value * 100

        if rec.get("status") == MarketSnapshot.STATUS_ERROR:
            if MarketSnapshot.objects.filter(
                report_date=report_date,
                source_name=rec["source_name"],
                status=MarketSnapshot.STATUS_OK,
            ).exists():
                return  # keep existing good record

        MarketSnapshot.objects.update_or_create(
            report_date=report_date,
            source_name=rec["source_name"],
            defaults={
                "fetched_at_jst": fetched_at,
                "source_url": rec.get("source_url", ""),
                "value": rec.get("value"),
                "unit": rec.get("unit", ""),
                "change_vs_prev_bd": rec.get("change_vs_prev_bd"),
                "change_vs_prev_bd_pct": rec.get("change_vs_prev_bd_pct"),
                "note": rec.get("note", ""),
                "status": rec.get("status", MarketSnapshot.STATUS_OK),
                "error_message": rec.get("error_message", ""),
            },
        )

    def _run(source_name, source_url, fetcher, *args):
        try:
            _persist(fetcher(*args))
        except Exception as exc:
            _persist({
                "source_name": source_name,
                "source_url": source_url,
                "value": None,
                "unit": "",
                "note": "",
                "status": MarketSnapshot.STATUS_ERROR,
                "error_message": str(exc),
            })

    # UST 10Y / 20Y (US Treasury site)
    try:
        data = services.fetch_treasury_yield(prev_bd)
        for key, val in data["detail"].items():
            _persist({
                "source_name": key,
                "source_url": data["source_url"],
                "value": val,
                "unit": "%",
                "note": data["note"],
            })
    except Exception as exc:
        _persist({
            "source_name": "ust_10y_yield",
            "source_url": services.TREASURY_URL,
            "value": None, "unit": "%", "note": "",
            "status": MarketSnapshot.STATUS_ERROR,
            "error_message": str(exc),
        })

    _run("ust_30y_yield",     services.YFJP_TYX_URL,    services.fetch_ust30y_yfjp,      prev_bd)
    _run("DJIA Close",        services.YFJP_DJI_URL,    services.fetch_dji_close_yfjp,   prev_bd)
    _run("USDJPY 8:30",       services.YFJP_USDJPY_URL, services.fetch_usdjpy_yfjp,      prev_bd)
    _run("Gold Settlement",   services.GOLD_API_URL,    services.fetch_gold_yf_api,      prev_bd)
    _run("Tanaka Gold 14:00", services.TANAKA_URL,      services.fetch_tanaka_gold_1400, prev_bd)
