import uuid

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from accounts.crypto import parse_jwt
from accounts.models import User


class BearerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0] != b"Bearer":
            raise AuthenticationFailed("Sign in again.")
        try:
            claims = parse_jwt(parts[1].decode())
            user = User.objects.get(pk=uuid.UUID(claims["sub"]), is_active=True)
        except (ValueError, UnicodeError, User.DoesNotExist) as exc:
            raise AuthenticationFailed("Sign in again.") from exc
        return user, claims

    def authenticate_header(self, request):
        return "Bearer"


class BearerSchema(OpenApiAuthenticationExtension):
    target_class = "accounts.authentication.BearerAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
