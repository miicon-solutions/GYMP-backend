import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.exceptions import ValidationError

from accounts.crypto import normalize_phone
from accounts.identifiers import next_display
from accounts.models import StaffProfile, User
from accounts.seed_super import SEED_SUPER_SHORT_ID
from accounts.services import begin_mfa


class Command(BaseCommand):
    help = (
        "Create a super admin; optionally grant password-based browser operator access. "
        "Repeat for each additional super admin."
    )

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--browser-access", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            phone = normalize_phone(options["phone"])
        except ValidationError as exc:
            raise CommandError("Enter a valid super admin phone number.") from exc
        if User.objects.filter(phone_e164=phone).exists():
            raise CommandError("That phone is already registered.")
        password = None
        if options["browser_access"]:
            password = getpass.getpass("New operator password: ")
            if password != getpass.getpass("Confirm password: "):
                raise CommandError("Passwords do not match.")
            validate_password(password)
        user = User.objects.create_user(
            phone,
            password,
            full_name=options["name"],
            role="admin",
            is_superuser=True,
            is_staff=options["browser_access"],
        )
        short_id = (
            SEED_SUPER_SHORT_ID
            if not StaffProfile.objects.filter(short_id=SEED_SUPER_SHORT_ID).exists()
            else next_display("staff")
        )
        StaffProfile.objects.create(user=user, short_id=short_id)
        setup = begin_mfa(user)
        self.stdout.write(
            self.style.SUCCESS("Super admin created. Keep this one-time MFA setup token private:")
        )
        self.stdout.write(setup["setup_token"])
