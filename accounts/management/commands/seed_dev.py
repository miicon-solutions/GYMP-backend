from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from operations.services import seed_hours
from plans.models import Plan


class Command(BaseCommand):
    help = "Seed development plans and default gym hours; never creates credentials."

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
