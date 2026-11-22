from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from notifications.services import (
    OPS_ALERT_DIGEST_TIMEZONES,
    notify_admin_daily_enrollments,
    notify_admin_daily_enrollments_all,
)


class Command(BaseCommand):
    help = (
        "Send end-of-day admin enrollment digests for Asia/Dhaka and/or "
        "Europe/London. Run ~23:55 in each zone via host cron."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Override calendar date YYYY-MM-DD (tests / backfill).",
        )
        parser.add_argument(
            "--timezone",
            choices=list(OPS_ALERT_DIGEST_TIMEZONES),
            help="Single zone. Omit (or pass --all) to run Dhaka + London.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Run both Asia/Dhaka and Europe/London (default when --timezone omitted).",
        )

    def handle(self, *args, **options):
        for_date = None
        if options.get("date"):
            try:
                for_date = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("--date must be YYYY-MM-DD") from exc

        tz = options.get("timezone")
        if tz and not options.get("all"):
            result = notify_admin_daily_enrollments(for_date=for_date, tz_name=tz)
            self.stdout.write(self.style.SUCCESS(f"Admin daily enrollments: {result}"))
            return

        results = notify_admin_daily_enrollments_all(for_date=for_date)
        self.stdout.write(self.style.SUCCESS(f"Admin daily enrollments: {results}"))
