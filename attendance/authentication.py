import secrets
from types import SimpleNamespace

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class DeviceAuthentication(BaseAuthentication):
    def authenticate(self, request):
        raw = request.headers.get("X-Device-Key", "")
        if not settings.ATTENDANCE_DEVICE_KEY or not secrets.compare_digest(
            raw.encode(), settings.ATTENDANCE_DEVICE_KEY.encode()
        ):
            raise AuthenticationFailed("Device access denied.")
        return SimpleNamespace(is_authenticated=True), None

    def authenticate_header(self, request):
        return "X-Device-Key"


class DeviceSchema(OpenApiAuthenticationExtension):
    target_class = "attendance.authentication.DeviceAuthentication"
    name = "deviceKey"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-Device-Key"}
