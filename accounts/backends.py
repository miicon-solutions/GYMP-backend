"""Local/dev authentication helpers for the operator console."""

from django.conf import settings
from django.contrib.auth.backends import ModelBackend

from accounts.seed_super import SEED_OPERATOR_USERNAME, SEED_SUPER_PHONE


class SeedOperatorBackend(ModelBackend):
    """Map fixed local username ``gym-pm`` to the seed super phone account."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if settings.APP_ENV == "prod" or not username or password is None:
            return None
        if username.strip() != SEED_OPERATOR_USERNAME:
            return None
        from accounts.models import User

        user = User.objects.filter(phone_e164=SEED_SUPER_PHONE).first()
        if user is None or not user.check_password(password):
            return None
        return user if self.user_can_authenticate(user) else None
