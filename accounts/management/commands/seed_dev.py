from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.seed_super import (
    SEED_OPERATOR_PASSWORD,
    SEED_OPERATOR_USERNAME,
    SEED_SUPER_PHONE,
    SEED_SUPER_SHORT_ID,
    ensure_seed_super_admin,
)
from operations.services import seed_hours
from plans.models import Plan


class Command(BaseCommand):
    help = (
        "Seed development plans, default gym hours, and the Go-parity seed super admin "
        f"({SEED_SUPER_PHONE} / {SEED_SUPER_SHORT_ID}; browser "
        f"{SEED_OPERATOR_USERNAME} / {SEED_OPERATOR_PASSWORD}). Disabled in production."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        if settings.APP_ENV == "prod":
            raise CommandError("Development seed data is disabled in production.")
        seed_hours()
        for catalog, months, rate, reduction in [
            ("monthly", 1, 1500, 0),
            ("quarterly", 3, 1500, 500),
            ("annual", 12, 1500, 3500),
        ]:
            Plan.objects.get_or_create(
                duration_months=months,
                defaults={
                    "catalog_id": catalog,
                    "name": catalog.title(),
                    "monthly_rate_taka": rate,
                    "admission_fee_taka": 1500,
                    "discount_type": "amount" if reduction else "none",
                    "discount_value": reduction,
                },
            )
        self.stdout.write(self.style.SUCCESS("Development plans and gym hours are ready."))
        result = ensure_seed_super_admin()
        browser = f"Browser /admin/ login: {SEED_OPERATOR_USERNAME} / {SEED_OPERATOR_PASSWORD}."
        if result.status == "created":
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seed super admin created ({SEED_SUPER_PHONE} / {SEED_SUPER_SHORT_ID}). "
                    f"{browser} Keep this one-time MFA setup token private:"
                )
            )
            self.stdout.write(result.setup_token)
        elif result.status == "reclaimed":
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seed super admin reclaimed from member ({SEED_SUPER_PHONE}). "
                    f"{browser} Keep this one-time MFA setup token private:"
                )
            )
            self.stdout.write(result.setup_token)
        elif result.status == "refreshed":
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seed super admin MFA setup token refreshed ({SEED_SUPER_PHONE}). "
                    f"{browser} Keep this one-time MFA setup token private:"
                )
            )
            self.stdout.write(result.setup_token)
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seed super admin ready ({SEED_SUPER_PHONE} / "
                    f"{result.user.staff_profile.short_id}). {browser}"
                )
            )
