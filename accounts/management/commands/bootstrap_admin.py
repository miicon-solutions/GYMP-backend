import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import StaffProfile, User
from accounts.services import begin_mfa


class Command(BaseCommand):
    help = (
        "Create the initial super admin; optionally grant password-based browser operator access."
    )

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--browser-access", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists():
            raise CommandError(
                "A super admin already exists. Use authorized staff operations for enrollment."
            )
        password = None
        if options["browser_access"]:
            password = getpass.getpass("New operator password: ")
            if password != getpass.getpass("Confirm password: "):
                raise CommandError("Passwords do not match.")
            validate_password(password)
        user = User.objects.create_user(
            options["phone"],
            password,
            full_name=options["name"],
            role="admin",
            is_superuser=True,
            is_staff=options["browser_access"],
        )
        StaffProfile.objects.create(user=user, short_id="S-ADM-7400")
        setup = begin_mfa(user)
        self.stdout.write(
            self.style.SUCCESS("Super admin created. Keep this one-time MFA setup token private:")
        )
        self.stdout.write(setup["setup_token"])
