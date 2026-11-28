from django.core.management.base import BaseCommand

from notifications.models import MemberNotification
from notifications.services import notify_staff_cash_request
from payments.models import CashPaymentRequest


class Command(BaseCommand):
    help = (
        "Create staff inbox + FCM for pending cash requests that have no "
        "cash_request notification rows yet. Idempotent via unique "
        "(user, code, related_object_id)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List requests that would be notified without writing.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        pending = CashPaymentRequest.objects.filter(status="pending").select_related(
            "member__user"
        )
        scanned = 0
        skipped = 0
        notified = 0
        for req in pending.iterator():
            scanned += 1
            if MemberNotification.objects.filter(
                code="cash_request",
                related_object_id=str(req.pk),
            ).exists():
                skipped += 1
                continue
            name = (req.member.user.full_name or "").strip() or req.member.member_id
            if dry_run:
                self.stdout.write(
                    f"Would notify req={req.pk} member={name!r} amount={req.amount_taka}"
                )
                notified += 1
                continue
            result = notify_staff_cash_request(req.pk)
            self.stdout.write(
                f"Notified req={req.pk} member={name!r} amount={req.amount_taka} → {result}"
            )
            notified += 1
        verb = "Would notify" if dry_run else "Notified"
        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill done: scanned={scanned} skipped_existing={skipped} "
                f"{verb.lower()}={notified} dry_run={dry_run}"
            )
        )
