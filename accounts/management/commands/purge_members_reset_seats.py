"""Delete all members and member-related history; reset ID sequences and offer seats."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Challenge, DisplaySequence, User
from attendance.models import CheckIn
from biometrics.models import (
    BridgeDeviceJob,
    FingerprintDeviceSyncState,
    MemberBiometricTemplate,
)
from members.models import MemberProfile
from notifications.models import StaffAnnouncement
from operations.models import Activity
from payments.models import CashPaymentRequest, Payment, PaymentSession
from plans.models import Offer


class Command(BaseCommand):
    help = (
        "Delete every member user and all member-related history, reset "
        "member/member_temporary display sequences to 0, and set active limited "
        "offers to 250 seats. Staff, plans, and device architecture are kept."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required. Without this flag the command is a no-op dry description.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Refusing to run without --confirm.")

        members = list(
            User.objects.filter(role="member").select_related("member_profile")
        )
        member_user_ids = [u.pk for u in members]
        member_user_id_strs = {str(pk) for pk in member_user_ids}
        phones = [u.phone_e164 for u in members if u.phone_e164]
        display_ids: set[str] = set()
        keypad_ids: set[str] = set()
        for user in members:
            profile = getattr(user, "member_profile", None)
            if profile is None:
                continue
            mid = (profile.member_id or "").strip()
            if mid:
                display_ids.add(mid)
            kid = (profile.device_keypad_id or "").strip()
            if kid:
                keypad_ids.add(kid)

        staff_before = User.objects.filter(role="admin").count()
        self.stdout.write(
            f"Purging {len(members)} members "
            f"(profiles={MemberProfile.objects.count()}, "
            f"payments={Payment.objects.count()}, "
            f"checkins={CheckIn.objects.count()})."
        )

        with transaction.atomic():
            deleted_users, _ = User.objects.filter(pk__in=member_user_ids).delete()

            # Orphan OTP challenges that only keyed off phone (actor may be null).
            if phones:
                Challenge.objects.filter(phone_e164__in=phones).delete()

            # Activity / announcements soft-reference members by UUID or display id.
            activity_ids = []
            for row in Activity.objects.all().iterator():
                params = row.summary_params if isinstance(row.summary_params, dict) else {}
                blob = json.dumps(params, default=str)
                if any(uid in blob for uid in member_user_id_strs):
                    activity_ids.append(row.pk)
                    continue
                if any(
                    token and token in blob
                    for token in (*display_ids, *keypad_ids)
                ):
                    activity_ids.append(row.pk)
            if activity_ids:
                Activity.objects.filter(pk__in=activity_ids).delete()

            if member_user_ids:
                StaffAnnouncement.objects.filter(member_id__in=member_user_ids).delete()

            job_ids = []
            for job in BridgeDeviceJob.objects.all().iterator():
                blob = json.dumps(
                    {"payload": job.payload or {}, "result": job.result or {}},
                    default=str,
                )
                if any(uid in blob for uid in member_user_id_strs):
                    job_ids.append(job.pk)
                    continue
                if any(token and token in blob for token in (*display_ids, *keypad_ids)):
                    job_ids.append(job.pk)
                    continue
                # Catch PF-/PFT-/PG- display ids left in payloads after wipe.
                for token in ("PF-", "PFT-", "PG-"):
                    if token in blob and "ADM-" not in blob and "SADM-" not in blob:
                        # Prefer explicit match on known display prefixes for members.
                        payload = job.payload if isinstance(job.payload, dict) else {}
                        user_id = str(payload.get("user_id") or payload.get("display_id") or "")
                        if user_id.upper().startswith(("PF-", "PFT-", "PG-")):
                            job_ids.append(job.pk)
                            break
            if job_ids:
                BridgeDeviceJob.objects.filter(pk__in=job_ids).delete()

            # Safety net if any non-CASCADE edge left profiles/payments behind.
            leftover_profiles = MemberProfile.objects.count()
            if leftover_profiles:
                MemberProfile.objects.all().delete()

            Payment.objects.all().delete()
            PaymentSession.objects.all().delete()
            CashPaymentRequest.objects.all().delete()
            CheckIn.objects.all().delete()
            MemberBiometricTemplate.objects.all().delete()
            FingerprintDeviceSyncState.objects.all().delete()

            for name in ("member", "member_temporary"):
                DisplaySequence.objects.update_or_create(name=name, defaults={"value": 0})

            offer_updated = Offer.objects.filter(
                is_active=True, max_redemptions__isnull=False
            ).update(max_redemptions=250)

        staff_after = User.objects.filter(role="admin").count()
        if staff_after != staff_before:
            raise CommandError(
                f"Staff count changed during purge ({staff_before} → {staff_after})."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"users_deleted≈{deleted_users}, "
                f"members={User.objects.filter(role='member').count()}, "
                f"profiles={MemberProfile.objects.count()}, "
                f"payments={Payment.objects.count()}, "
                f"checkins={CheckIn.objects.count()}, "
                f"templates={MemberBiometricTemplate.objects.count()}, "
                f"offers_capped_250={offer_updated}, "
                f"staff={staff_after}."
            )
        )
