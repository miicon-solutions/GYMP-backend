"""Daily reconcile: revoke expired scanner users; restore active+ready vault members."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from biometrics.services import reconcile_device_access


class Command(BaseCommand):
    help = (
        "Reconcile fingerprint device access with membership status: "
        "soft-delete expired members on the scanner; re-push vault for active+ready. "
        "Run daily via host cron in Asia/Dhaka (after notify_membership_expiry)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Override local date YYYY-MM-DD (tests / backfill).",
        )

    def handle(self, *args, **options):
        today = None
        if options.get("date"):
            today = timezone.datetime.strptime(options["date"], "%Y-%m-%d").date()
        result = reconcile_device_access(today=today)
        self.stdout.write(
            self.style.SUCCESS(
                "Device access reconcile: "
                f"flipped={result.get('flipped', 0)} "
                f"revoked={result['revoked']} restored={result['restored']} "
                f"skipped={result['skipped']} errors={len(result.get('errors') or [])}"
            )
        )
