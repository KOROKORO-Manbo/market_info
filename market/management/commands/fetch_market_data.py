from django.core.management.base import BaseCommand

from market import services
from market.refresh import refresh_all


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

        self.stdout.write(f"report_date : {report_date}")
        self.stdout.write("")
        refresh_all(report_date)
        self.stdout.write(self.style.SUCCESS("Done."))
