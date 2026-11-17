import base64
import hashlib
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _key() -> bytes:
    raw = (settings.BIOMETRIC_ENCRYPTION_KEY or "").strip()
    if not raw:
        raise ImproperlyConfigured("BIOMETRIC_ENCRYPTION_KEY or TOTP_ENCRYPTION_KEY is required.")
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
        raise ImproperlyConfigured("BIOMETRIC_ENCRYPTION_KEY must encode 32 bytes.") from exc


def encrypt_bytes(data: bytes) -> str:
    nonce = secrets.token_bytes(12)
    return base64.b64encode(nonce + AESGCM(_key()).encrypt(nonce, data, None)).decode()


def decrypt_bytes(value: str) -> bytes:
    raw = base64.b64decode(value)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
