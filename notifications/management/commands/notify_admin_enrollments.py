from django.core.management.base import BaseCommand

from notifications.services import notify_admin_enrollments_batch


class Command(BaseCommand):
    help = (
        "Fan out admin_enrollment push/inbox rows for new first payments. "
        "Run every 5–15 minutes via host cron in Asia/Dhaka (recommended */10)."
    )

    def handle(self, *args, **options):
        result = notify_admin_enrollments_batch()
        self.stdout.write(self.style.SUCCESS(f"Admin enrollment alerts: {result}"))
