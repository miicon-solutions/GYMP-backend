import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, ValidationError


def normalize_phone(value):
    value = str(value).strip()
    if not re.fullmatch(r"\+8801[3-9][0-9]{8}", value):
        raise ValidationError({"phone_e164": "Enter a valid phone number."})
    return value


def digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def matches(raw, expected):
    return hmac.compare_digest(digest(raw), expected)


def encryption_key():
    raw = settings.TOTP_ENCRYPTION_KEY.strip()
    try:
        if len(raw.encode()) == 32:
            key = raw.encode()
        elif len(raw) == 64:
            key = bytes.fromhex(raw)
        else:
            key = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=True)
        if len(key) != 32:
            raise ValueError
        return key
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured("TOTP_ENCRYPTION_KEY must encode 32 bytes.") from exc


def encrypt_secret(value):
    nonce = secrets.token_bytes(12)
    return base64.b64encode(
        nonce + AESGCM(encryption_key()).encrypt(nonce, value.encode(), None)
    ).decode()


def decrypt_secret(value):
    raw = base64.b64decode(value)
    return AESGCM(encryption_key()).decrypt(raw[:12], raw[12:], None).decode()


def issue_jwt(user, typ="access", **extra):
    now = timezone.now()
    ttl = settings.JWT_ACCESS_TTL_SEC if typ == "access" else 900
    claims = {
        "sub": str(user.pk),
        "role": user.role,
        "typ": typ,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": secrets.token_hex(16),
        **extra,
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def parse_jwt(raw, typ="access"):
    try:
        claims = jwt.decode(
            raw,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat", "typ"]},
        )
        if claims["typ"] != typ:
            raise jwt.InvalidTokenError()
        return claims
    except (jwt.InvalidTokenError, TypeError) as exc:
        raise AuthenticationFailed("Your session expired. Sign in again.") from exc
