from functools import lru_cache

import httpx
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, NotFound

from core.api import BadGateway


def send_sms_message(phone, msg: str) -> None:
    if not settings.SMS_NET_BD_API_KEY:
        raise BadGateway("Text message service is unavailable.")
    form = {
        "api_key": settings.SMS_NET_BD_API_KEY,
        "to": phone.lstrip("+"),
        "msg": msg,
    }
    if settings.SMS_NET_BD_SENDER_ID:
        form["sender_id"] = settings.SMS_NET_BD_SENDER_ID
    try:
        response = httpx.post("https://api.sms.net.bd/sendsms", data=form, timeout=10)
        response.raise_for_status()
        body = response.json()
        if body.get("error") != 0:
            raise ValueError
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise BadGateway("Text message service is unavailable.") from exc


def send_sms(phone, code):
    """OTP verification SMS only. Honors OTP_DEV_BYPASS; notification SMS must use send_sms_message."""
    if settings.OTP_DEV_BYPASS:
        return
    send_sms_message(
        phone,
        f"Your Pure Fitness verification code is {code}. Do not share this code.",
    )


def google_sign_in_enabled():
    return bool(settings.FIREBASE_CREDENTIALS_FILE)


@lru_cache(maxsize=1)
def firebase_app():
    import firebase_admin
    from firebase_admin import credentials

    path = settings.FIREBASE_CREDENTIALS_FILE
    if not path:
        raise RuntimeError("Firebase credentials are not configured.")
    return firebase_admin.initialize_app(credentials.Certificate(path), name="gyma")


def verify_google(raw):
    from firebase_admin import auth

    if not google_sign_in_enabled():
        raise NotFound("Google sign-in is not available.")
    try:
        result = auth.verify_id_token(raw, app=firebase_app(), check_revoked=True)
        if (
            result.get("firebase", {}).get("sign_in_provider") != "google.com"
            or not result.get("email_verified")
            or not result.get("email")
            or not result.get("uid")
        ):
            raise ValueError
        return result
    except (
        ValueError,
        auth.InvalidIdTokenError,
        auth.RevokedIdTokenError,
        auth.UserDisabledError,
    ) as exc:
        raise AuthenticationFailed("Google sign-in failed. Try again.") from exc
    except Exception as exc:
        raise BadGateway("Google sign-in is unavailable. Try again.") from exc
