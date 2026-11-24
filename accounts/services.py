import secrets
from datetime import timedelta

import pyotp
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)

from accounts import providers
from accounts.crypto import (
    decrypt_secret,
    digest,
    encrypt_secret,
    issue_jwt,
    matches,
    normalize_phone,
    parse_jwt,
)
from accounts.identifiers import next_display
from accounts.models import (
    Challenge,
    GoogleLinkSession,
    RateBucket,
    RefreshSession,
    StaffProfile,
    User,
)
from core.api import Conflict, require_admin
from members.models import MemberProfile


def lock_key(key):
    # Serializes operations even when the phone/session row does not exist yet.
    if connection.vendor != "postgresql":
        return
    value = int(digest(key)[:15], 16)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [value])


def throttle(key, limit, seconds):
    now = timezone.now()
    error = False
    with transaction.atomic():
        lock_key("rate:" + key)
        bucket, _ = RateBucket.objects.get_or_create(key=digest(key), defaults={"starts_at": now})
        if now >= bucket.starts_at + timedelta(seconds=seconds):
            bucket.starts_at, bucket.count = now, 0
        if bucket.count >= limit:
            error = True
        else:
            bucket.count += 1
            bucket.save()
    if error:
        raise Throttled(wait=seconds)


@transaction.atomic
def new_member(phone, **values):
    user = User.objects.create_user(phone, role="member", **values)
    MemberProfile.objects.create(user=user, member_id=next_display("member"))
    return user


def member_data(user):
    p = MemberProfile.objects.get(user=user)
    return {
        "id": str(user.pk),
        "member_id": p.member_id,
        "phone_e164": user.phone_e164,
        "full_name": user.full_name,
        "email": user.email or None,
        "signed_in_with_google": bool(user.firebase_uid),
        "profile_complete": p.profile_complete,
        "membership_status": p.membership_status,
    }


def staff_data(user):
    p = StaffProfile.objects.get(user=user)
    return {
        "id": str(user.pk),
        "short_id": p.short_id,
        "name": user.full_name,
        "phone_e164": user.phone_e164,
        "is_super": user.is_superuser,
        "is_active": user.is_active,
        "mfa_enrolled": bool(p.mfa_enrolled_at),
    }


def issue_tokens(user):
    if not user.is_active:
        raise PermissionDenied("This account is inactive.")
    refresh = secrets.token_hex(32)
    RefreshSession.objects.create(
        user=user,
        token_hash=digest(refresh),
        expires_at=timezone.now() + timedelta(seconds=settings.JWT_REFRESH_TTL_SEC),
    )
    return {
        "access_token": issue_jwt(user),
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in_sec": settings.JWT_ACCESS_TTL_SEC,
        "member" if user.role == "member" else "staff": member_data(user)
        if user.role == "member"
        else staff_data(user),
    }


def resolve_phone(phone):
    user = User.objects.filter(phone_e164=phone).first()
    result = {"phone_e164": phone, "kind": "unknown"}
    if user:
        if not user.is_active:
            raise PermissionDenied("This account is inactive.")
        result["kind"] = "staff" if user.role == "admin" else "member"
        if user.role == "admin":
            result.update(
                staff_short_id=user.staff_profile.short_id,
                mfa_enrolled=bool(user.staff_profile.mfa_enrolled_at),
            )
    return result


def check_proof(user, raw, kind):
    claims = parse_jwt(raw, "phone_proof")
    if claims["sub"] != str(user.pk) or claims.get("purpose") != kind:
        raise ValidationError({"phone_proof_token": "Verify your phone again."})
    return claims


def ensure_new_phone(user, phone):
    if user.phone_e164 == phone:
        raise ValidationError({"phone_e164": "Choose a different number."})
    if User.objects.filter(phone_e164=phone).exists():
        raise Conflict("Phone number is already registered.")


def send_otp(data, actor=None):
    phone, purpose = data["phone_e164"], data["purpose"]
    target = None
    if purpose in ("confirmCurrentPhone", "changePhone"):
        if not actor or actor.role != "member":
            raise AuthenticationFailed("Sign in to continue.")
        if purpose == "confirmCurrentPhone" and actor.phone_e164 != phone:
            raise ValidationError({"phone_e164": "Enter your current phone number."})
        if purpose == "changePhone":
            claims = check_proof(actor, data.get("current_phone_proof", ""), "confirmCurrentPhone")
            if claims.get("phone_e164") != actor.phone_e164:
                raise ValidationError({"current_phone_proof": "Verify your phone again."})
            ensure_new_phone(actor, phone)
    elif purpose == "adminLinkMemberPhone":
        require_admin(actor)
        target = User.objects.filter(pk=data.get("target_member_id"), role="member").first()
        if not target:
            raise NotFound("Member not found.")
        ensure_new_phone(target, phone)
    elif purpose != "onboarding":
        raise ValidationError({"purpose": "Choose a valid purpose."})
    if User.objects.filter(phone_e164=phone, role="admin").exists():
        raise Conflict("Phone number is already used by staff.")
    throttle("sms:" + phone, 10, 3600)
    now = timezone.now()
    with transaction.atomic():
        lock_key("otp:" + phone + purpose)
        latest = Challenge.objects.filter(
            phone_e164=phone, purpose=purpose, consumed_at=None, expires_at__gt=now
        ).first()
        if latest and now < latest.resend_at:
            raise Throttled(wait=max(1, int((latest.resend_at - now).total_seconds())))
        Challenge.objects.filter(phone_e164=phone, purpose=purpose, consumed_at=None).update(
            consumed_at=now
        )
        code = (
            settings.OTP_DEV_MASTER_CODE
            if settings.OTP_DEV_BYPASS
            else f"{secrets.randbelow(1000000):06d}"
        )
        challenge = Challenge(
            phone_e164=phone,
            purpose=purpose,
            actor=actor if purpose != "onboarding" else None,
            target=target,
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SEC),
            resend_at=now + timedelta(seconds=settings.OTP_RESEND_SEC),
        )
        challenge.code_hash = digest(f"{challenge.pk}:{code}")
        challenge.save()
    if not settings.OTP_DEV_BYPASS:
        try:
            providers.send_sms(phone, code)
        except Exception:
            Challenge.objects.filter(pk=challenge.pk).update(consumed_at=timezone.now())
            raise
    return {
        "otp_session_id": str(challenge.pk),
        "phone_e164": phone,
        "purpose": purpose,
        "expires_in_sec": settings.OTP_TTL_SEC,
        "resend_after_sec": settings.OTP_RESEND_SEC,
        "dev_bypass": settings.OTP_DEV_BYPASS,
    }


def consume_challenge(session_id, code, purposes, actor=None, target=None):
    error = None
    with transaction.atomic():
        row = Challenge.objects.select_for_update().filter(pk=session_id).first()
        if (
            not row
            or row.purpose not in purposes
            or row.actor_id != getattr(actor, "pk", None)
            or row.target_id != getattr(target, "pk", None)
        ):
            raise NotFound("Verification not found.")
        now = timezone.now()
        if row.consumed_at or now >= row.expires_at:
            raise ValidationError({"code": "This code has expired or was already used."})
        if row.attempts >= 5:
            raise Throttled(wait=settings.OTP_TTL_SEC)
        if not matches(f"{row.pk}:{code}", row.code_hash):
            row.attempts += 1
            row.save(update_fields=["attempts"])
            error = ValidationError({"code": "Invalid code."})
        else:
            row.consumed_at = now
            row.save(update_fields=["consumed_at"])
    if error:
        raise error
    return row


def verify_otp(data, actor):
    row = Challenge.objects.filter(pk=data["otp_session_id"]).first()
    if not row:
        raise NotFound("Verification not found.")
    if row.purpose == "adminLinkMemberPhone":
        raise ValidationError({"otp_session_id": "Use the member phone-link endpoint."})
    purposes = (
        ["onboarding"] if row.purpose == "onboarding" else ["confirmCurrentPhone", "changePhone"]
    )
    bound_actor = None if row.purpose == "onboarding" else actor
    row = consume_challenge(row.pk, data["code"], purposes, bound_actor)
    if row.purpose != "onboarding":
        return {
            "phone_proof_token": issue_jwt(
                actor, "phone_proof", purpose=row.purpose, phone_e164=row.phone_e164
            ),
            "proof_kind": row.purpose,
            "phone_e164": row.phone_e164,
        }
    with transaction.atomic():
        lock_key("phone:" + row.phone_e164)
        user = User.objects.filter(phone_e164=row.phone_e164).first()
        if user and user.role != "member":
            raise Conflict("Phone number is already registered.")
        user = user or new_member(row.phone_e164)
        return issue_tokens(user)


def public_config():
    return {"google_sign_in": providers.google_sign_in_enabled()}


def google_login(raw):
    identity = providers.verify_google(raw)
    user = User.objects.filter(firebase_uid=identity["uid"], role="member").first()
    if user:
        return {"status": "authenticated", **issue_tokens(user)}
    if User.objects.filter(email__iexact=identity["email"]).exists():
        raise Conflict("Sign in with your phone to link Google.")
    row = GoogleLinkSession.objects.create(
        firebase_uid=identity["uid"],
        email=identity["email"],
        full_name=identity.get("name", ""),
        expires_at=timezone.now() + timedelta(seconds=settings.GOOGLE_LINK_TTL_SEC),
    )
    return {
        "status": "needsPhoneLink",
        "google_session_id": str(row.pk),
        "email": row.email,
        "full_name": row.full_name,
    }


def bind_google(user, identity):
    if user.role != "member":
        raise PermissionDenied()
    if user.firebase_uid and user.firebase_uid != identity["uid"]:
        raise Conflict("A different Google account is already linked.")
    if (
        User.objects.exclude(pk=user.pk).filter(firebase_uid=identity["uid"]).exists()
        or User.objects.exclude(pk=user.pk).filter(email__iexact=identity["email"]).exists()
    ):
        raise Conflict("Google account is already linked.")
    user.firebase_uid, user.email = identity["uid"], identity["email"].strip().lower()
    if not user.full_name:
        user.full_name = identity.get("name", "")
    user.save()
    return member_data(user)


def link_google_phone(data):
    if not providers.google_sign_in_enabled():
        raise NotFound("Google sign-in is not available.")
    pending = GoogleLinkSession.objects.filter(
        pk=data["google_session_id"], consumed_at=None, expires_at__gt=timezone.now()
    ).first()
    if not pending:
        raise ValidationError({"google_session_id": "Sign in with Google again."})
    otp = consume_challenge(data["otp_session_id"], data["code"], ["onboarding"])
    with transaction.atomic():
        pending = GoogleLinkSession.objects.select_for_update().get(pk=pending.pk)
        if pending.consumed_at or pending.expires_at <= timezone.now():
            raise ValidationError({"google_session_id": "Sign in with Google again."})
        lock_key("phone:" + otp.phone_e164)
        lock_key("google:" + pending.firebase_uid)
        user = User.objects.filter(phone_e164=otp.phone_e164).first() or new_member(otp.phone_e164)
        bind_google(
            user, {"uid": pending.firebase_uid, "email": pending.email, "name": pending.full_name}
        )
        pending.consumed_at = timezone.now()
        pending.save()
        return issue_tokens(user)


def rotate_refresh(raw):
    with transaction.atomic():
        row = (
            RefreshSession.objects.select_for_update()
            .filter(token_hash=digest(raw), revoked_at=None, expires_at__gt=timezone.now())
            .first()
        )
        if not row:
            raise AuthenticationFailed("Your session expired. Sign in again.")
        user = User.objects.select_for_update().get(pk=row.user_id)
        if not user.is_active:
            raise AuthenticationFailed("This account is inactive.")
        row.revoked_at = timezone.now()
        row.save(update_fields=["revoked_at"])
        return issue_tokens(user)


def begin_mfa(user):
    raw = secrets.token_hex(24)
    p = StaffProfile.objects.get(user=user)
    p.totp_secret_encrypted, p.mfa_enrolled_at, p.totp_last_step = "", None, None
    p.setup_token_hash = digest(raw)
    p.setup_expires_at = timezone.now() + timedelta(seconds=settings.MFA_SETUP_TTL_SEC)
    p.save()
    return {
        "staff_id": str(user.pk),
        "setup_token": raw,
        "expires_in_sec": settings.MFA_SETUP_TTL_SEC,
    }


def mfa_action(data, action):
    phone = normalize_phone(data["phone_e164"])
    throttle("mfa:" + phone, 10, 60)
    with transaction.atomic():
        user = (
            User.objects.select_for_update()
            .filter(phone_e164=phone, role="admin", is_active=True)
            .first()
        )
        if not user:
            raise AuthenticationFailed("Unable to unlock. Check your details.")
        p = StaffProfile.objects.select_for_update().get(user=user)
        now = timezone.now()
        if action != "unlock":
            if (
                not p.setup_token_hash
                or not matches(data["setup_token"], p.setup_token_hash)
                or not p.setup_expires_at
                or now >= p.setup_expires_at
            ):
                raise ValidationError({"setup_token": "Setup expired. Ask your super admin."})
        if action == "setup":
            secret = pyotp.random_base32()
            p.totp_secret_encrypted = encrypt_secret(secret)
            p.save()
            return {
                "phone_e164": phone,
                "secret_base32": secret,
                "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(
                    name=p.short_id, issuer_name=settings.TOTP_ISSUER
                ),
                "issuer": settings.TOTP_ISSUER,
                "account_name": p.short_id,
            }
        if not p.totp_secret_encrypted or (action == "unlock" and not p.mfa_enrolled_at):
            raise PermissionDenied("Set up your authenticator first.")
        totp = pyotp.TOTP(decrypt_secret(p.totp_secret_encrypted))
        step = int(now.timestamp()) // 30
        accepted = next(
            (
                s
                for s in (step, step - 1, step + 1)
                if secrets.compare_digest(totp.at(s * 30), data["totp_code"])
            ),
            None,
        )
        if accepted is None or (p.totp_last_step is not None and accepted <= p.totp_last_step):
            raise AuthenticationFailed("Invalid code. Try again.")
        p.totp_last_step = accepted
        if action == "confirm":
            p.mfa_enrolled_at, p.setup_token_hash, p.setup_expires_at = now, "", None
        p.save()
        return issue_tokens(user)


@transaction.atomic
def register_user(data):
    email = data.get("email", "").strip().lower()
    password = data.get("password")
    full_name = data.get("full_name", "").strip()
    phone = data.get("phone_e164", "").strip()

    if email and User.objects.filter(email__iexact=email).exists():
        raise ValidationError({"email": "User with this email already exists."})

    if phone:
        phone = normalize_phone(phone)
        if User.objects.filter(phone_e164=phone).exists():
            raise ValidationError({"phone_e164": "User with this phone number already exists."})
    else:
        from accounts.models import DisplaySequence

        seq_row, _ = DisplaySequence.objects.get_or_create(
            name="auto_phone", defaults={"value": 10000000}
        )
        seq_row.value += 1
        seq_row.save(update_fields=["value"])
        phone = f"+88019{seq_row.value:08d}"

    user = new_member(phone, email=email, full_name=full_name)
    user.set_password(password)
    user.save(update_fields=["password"])

    try:
        from fitness.services import get_profile

        get_profile(user)
    except Exception:
        pass

    tokens = issue_tokens(user)
    tokens["access"] = tokens["access_token"]
    tokens["refresh"] = tokens["refresh_token"]
    return tokens


def login_user(data):
    identifier = (data.get("email") or data.get("phone_e164") or data.get("username", "")).strip()
    password = data.get("password", "")
    if not identifier or not password:
        raise ValidationError({"detail": "Credentials required."})

    user = None
    if "@" in identifier:
        user = User.objects.filter(email__iexact=identifier).first()
    if not user:
        try:
            phone = normalize_phone(identifier)
            user = User.objects.filter(phone_e164=phone).first()
        except Exception:
            pass
    if not user:
        user = User.objects.filter(phone_e164=identifier).first()

    if not user or not user.check_password(password):
        raise AuthenticationFailed("Invalid email/phone or password.")
    if not user.is_active:
        raise PermissionDenied("This account is inactive.")

    tokens = issue_tokens(user)
    tokens["access"] = tokens["access_token"]
    tokens["refresh"] = tokens["refresh_token"]
    return tokens
