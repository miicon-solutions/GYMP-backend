import secrets

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from core.images import read_image
from fitness.models import AnthropometryLog, FitnessProfile


def get_profile(user):
    """Retrieve or lazily initialize the user's fitness profile."""
    if not user or not user.is_active:
        raise PermissionDenied("Authentication required.")
    profile, _ = FitnessProfile.objects.get_or_create(user=user)
    return profile


@transaction.atomic
def update_profile(user, data):
    profile = get_profile(user)
    fields = [
        "experience_level",
        "preferred_units",
        "daily_water_target_ml",
        "daily_calorie_target",
        "protein_target_g",
        "carbs_target_g",
        "fat_target_g",
    ]
    for field in fields:
        if field in data:
            setattr(profile, field, data[field])
    profile.save()
    return profile


@transaction.atomic
def log_anthropometry(user, data, photo_file=None):
    profile = get_profile(user)
    data = dict(data)
    if "weight_unit" not in data or not data["weight_unit"]:
        data["weight_unit"] = profile.weight_unit

    photo_name = None
    if photo_file:
        raw, ext = read_image(photo_file, "check_in_photo")
        photo_name = f"checkins/{secrets.token_hex(16)}.{ext}"
        saved_file = ContentFile(raw)
    else:
        saved_file = None

    log = AnthropometryLog(
        user=user,
        logged_at=data.get("logged_at", timezone.now()),
        weight=data["weight"],
        weight_unit=data["weight_unit"],
        body_fat_percentage=data.get("body_fat_percentage"),
        waist_inches=data.get("waist_inches"),
    )
    if photo_name and saved_file:
        log.check_in_photo.save(photo_name, saved_file, save=False)
    log.save()
    return log


def list_anthropometry(user):
    return AnthropometryLog.objects.filter(user=user).order_by("-logged_at", "-created_at")


def latest_anthropometry(user):
    return list_anthropometry(user).first()
