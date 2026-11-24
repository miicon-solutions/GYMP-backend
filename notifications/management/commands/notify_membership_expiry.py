from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.services import notify_membership_expiry_batch


class Command(BaseCommand):
    help = (
        "Create membership expiring (7d/1d) and expired notifications, "
        "and enqueue scanner revoke_access jobs when memberships flip to expired. "
        "Run daily via host cron in Asia/Dhaka "
        "(then optionally reconcile_device_access)."
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
        result = notify_membership_expiry_batch(today=today)
        self.stdout.write(self.style.SUCCESS(f"Notifications created: {result}"))
