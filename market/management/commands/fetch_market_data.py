from django.core.management.base import BaseCommand
from django.utils import timezone

from market.models import MarketSnapshot
from market import services


class Command(BaseCommand):
    help = "Fetch daily market data and save to MarketSnapshot."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Target report date (YYYY-MM-DD). Defaults to today (JST).",
        )

    def handle(self, *args, **options):
        if options["date"]:
            from datetime import date
            report_date = date.fromisoformat(options["date"])
        else:
            report_date = services.jst_now().date()

        prev_bd = services.previous_business_day(report_date)
        fetched_at = services.jst_now()

        self.stdout.write(f"report_date : {report_date}")
        self.stdout.write(f"prev_bd     : {prev_bd}")
        self.stdout.write("")

        tasks = [
            ("UST Yields",        self._fetch_treasury,    prev_bd),
            ("UST 30Y (SBI)",     self._fetch_ust30y,      prev_bd),
            ("DJIA Close",        self._fetch_dji,         prev_bd),
            ("USDJPY 8:30",       self._fetch_usdjpy,      prev_bd),
            ("Gold Settlement",   self._fetch_cme_gold,    prev_bd),
            ("Tanaka Gold 14:00", self._fetch_tanaka_gold, prev_bd),
        ]

        # 前日レコードをまとめて取得（change_vs_prev_bd 計算用）
        prev_snaps = {
            s.source_name: s
            for s in MarketSnapshot.objects.filter(
                report_date=prev_bd, status=MarketSnapshot.STATUS_OK
            )
        }

        saved = 0
        errors = 0
        skipped = 0
        for label, fetcher, date_arg in tasks:
            records = fetcher(date_arg)
            for rec in records:
                # ソースが前日比を返さない場合、前日のDBレコードから計算する
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

                is_error = rec.get("status") == MarketSnapshot.STATUS_ERROR

                if is_error:
                    # エラー時は既存の成功データを上書きしない
                    existing = MarketSnapshot.objects.filter(
                        report_date=report_date,
                        source_name=rec["source_name"],
                        status=MarketSnapshot.STATUS_OK,
                    ).first()
                    if existing:
                        self.stdout.write(self.style.WARNING(
                            f"  [skip]    {rec['source_name']}: fetch failed but keeping existing ok record"
                        ))
                        skipped += 1
                        continue

                _, created = MarketSnapshot.objects.update_or_create(
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
                action = "created" if created else "updated"
                if is_error:
                    self.stdout.write(self.style.ERROR(
                        f"  [ERROR]   {rec['source_name']}: {rec['error_message']}"
                    ))
                    errors += 1
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"  [{action:7}] {rec['source_name']}: {rec.get('value')} {rec.get('unit', '')}"
                    ))
                    saved += 1

        self.stdout.write("")
        self.stdout.write(f"Done — {saved} saved, {errors} errors.")

    # ------------------------------------------------------------------
    # Private helpers: each returns a list of record dicts
    # ------------------------------------------------------------------

    def _fetch_treasury(self, target_date):
        try:
            data = services.fetch_treasury_yield(target_date)
            return [
                {
                    "source_name": key,
                    "source_url": data["source_url"],
                    "value": val,
                    "unit": "%",
                    "note": data["note"],
                }
                for key, val in data["detail"].items()
            ]
        except Exception as e:
            return [self._error_record("UST 10Y/20Y", services.TREASURY_URL, e)]

    def _fetch_ust30y(self, target_date):
        try:
            return [services.fetch_ust30y_sbi(target_date)]
        except Exception as e:
            return [self._error_record("ust_30y_yield", services.SBI_PAGE_URL, e)]

    def _fetch_dji(self, target_date):
        try:
            data = services.fetch_dji_close(target_date)
            return [data]
        except Exception as e:
            return [self._error_record("DJIA Close", "", e)]

    def _fetch_usdjpy(self, target_date):
        try:
            data = services.fetch_usdjpy_0830(target_date)
            return [data]
        except Exception as e:
            return [self._error_record("USDJPY 8:30", services.USDJPY_URL, e)]

    def _fetch_cme_gold(self, target_date):
        try:
            data = services.fetch_cme_gold_settlement(target_date)
            return [data]
        except Exception as e:
            return [self._error_record("Gold Settlement", services.CME_GOLD_URL, e)]

    def _fetch_tanaka_gold(self, target_date):
        try:
            data = services.fetch_tanaka_gold_1400(target_date)
            return [data]
        except Exception as e:
            return [self._error_record("Tanaka Gold 14:00", services.TANAKA_URL, e)]

    @staticmethod
    def _error_record(source_name, source_url, exc):
        return {
            "source_name": source_name,
            "source_url": source_url,
            "value": None,
            "unit": "",
            "note": "",
            "status": MarketSnapshot.STATUS_ERROR,
            "error_message": str(exc),
        }
