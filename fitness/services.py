import secrets
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from core.images import read_image
from fitness.models import AnthropometryLog, FitnessProfile
from workouts.calculators import LBS_PER_KG, quantize

CM_PER_INCH = Decimal("2.54")


def _sync_body_from_member(user, profile: FitnessProfile) -> FitnessProfile:
    member_profile = getattr(user, "member_profile", None)
    if member_profile is None:
        return profile
    changed = []
    for attr in ("height_cm", "weight_kg", "age", "sex"):
        fp_val = getattr(profile, attr, None)
        mp_val = getattr(member_profile, attr, None)
        if (fp_val is None or fp_val == "") and (mp_val is not None and mp_val != ""):
            setattr(profile, attr, mp_val)
            changed.append(attr)
    if changed:
        profile.save(update_fields=[*changed, "updated_at"])
    return profile


def _sync_body_to_member(user, profile: FitnessProfile):
    member_profile = getattr(user, "member_profile", None)
    if member_profile is None:
        return
    changed = []
    for attr in ("height_cm", "weight_kg", "age", "sex"):
        fp_val = getattr(profile, attr, None)
        if fp_val is not None and fp_val != "" and getattr(member_profile, attr, None) != fp_val:
            setattr(member_profile, attr, fp_val)
            changed.append(attr)
    if changed:
        member_profile.save(update_fields=[*changed, "updated_at"])


def get_profile(user):
    """Retrieve or lazily initialize the user's fitness profile."""
    if not user or not user.is_active:
        raise PermissionDenied("Authentication required.")
    profile, _ = FitnessProfile.objects.get_or_create(user=user)
    return _sync_body_from_member(user, profile)


def get_effective_body_data(user, profile: FitnessProfile | None = None) -> dict:
    profile = profile or get_profile(user)
    member_profile = getattr(user, "member_profile", None)

    weight_kg = profile.weight_kg or (member_profile.weight_kg if member_profile else None)
    if not weight_kg:
        latest = AnthropometryLog.objects.filter(user=user).order_by("-logged_at", "-created_at").first()
        if latest:
            weight_kg = (
                latest.weight
                if latest.weight_unit == "kg"
                else quantize(Decimal(latest.weight) / LBS_PER_KG)
            )
    height_cm = profile.height_cm or (member_profile.height_cm if member_profile else None)
    age = profile.age or (member_profile.age if member_profile else None)
    sex = profile.sex or (member_profile.sex if member_profile else "") or ""

    has_body_data = bool(weight_kg and height_cm and age and sex)
    return {
        "weight_kg": float(weight_kg) if weight_kg else 70.0,
        "height_cm": float(height_cm) if height_cm else 170.0,
        "age": int(age) if age else 25,
        "sex": sex or "male",
        "raw_weight_kg": weight_kg,
        "raw_height_cm": height_cm,
        "raw_age": age,
        "raw_sex": sex,
        "has_body_data": has_body_data,
    }


def calculate_suggested_nutrition_targets(user, profile: FitnessProfile | None = None) -> dict:
    """Calculate suggested calories, macros, and water from synced body profile (Suggestion 9)."""
    profile = profile or get_profile(user)
    body = get_effective_body_data(user, profile)
    w = body["weight_kg"]
    h = body["height_cm"]
    a = body["age"]
    sex = body["sex"]
    goal = profile.nutrition_goal or "maintain_weight"

    if sex == "female":
        bmr = 10.0 * w + 6.25 * h - 5.0 * a - 161.0
        safe_min_cals = 1200
    elif sex == "other":
        bmr = 10.0 * w + 6.25 * h - 5.0 * a - 78.0
        safe_min_cals = 1350
    else:
        bmr = 10.0 * w + 6.25 * h - 5.0 * a + 5.0
        safe_min_cals = 1500

    tdee = max(bmr * 1.55, float(safe_min_cals))
    if goal == "lose_weight":
        raw_cals = tdee - 500.0
    elif goal == "gain_weight":
        raw_cals = tdee + 350.0
    else:
        raw_cals = tdee

    suggested_cals = max(safe_min_cals, int(round(raw_cals / 10.0) * 10))
    protein_mult = 2.0 if goal in ("lose_weight", "gain_weight") else 1.8
    suggested_protein = max(50, int(round(w * protein_mult)))
    suggested_fat = max(int(round(w * 0.8)), int(round((suggested_cals * 0.25) / 9.0)))
    remaining_carb_cals = max(200, suggested_cals - (suggested_protein * 4) - (suggested_fat * 9))
    suggested_carbs = max(50, int(round(remaining_carb_cals / 4.0)))
    suggested_water_ml = max(2000, min(8000, int(round((w * 35.0 + 500.0) / 50.0) * 50)))

    return {
        "goal": goal,
        "calories": suggested_cals,
        "protein_g": suggested_protein,
        "carbs_g": suggested_carbs,
        "fat_g": suggested_fat,
        "daily_water_target_ml": suggested_water_ml,
        "safe_minimum_calories": safe_min_cals,
        "has_body_data": body["has_body_data"],
        "weight_kg": body["weight_kg"],
        "height_cm": body["height_cm"],
        "age": body["age"],
        "sex": body["raw_sex"] or "male",
    }


def evaluate_target_warnings(profile: FitnessProfile, suggested: dict) -> list[dict]:
    """Return non-blocking warnings if any target is >20% away from suggested or below safe minimum."""
    warnings = []
    checks = [
        ("calories", "Calories", int(profile.daily_calorie_target), int(suggested["calories"])),
        ("protein_g", "Protein", int(profile.protein_target_g), int(suggested["protein_g"])),
        ("carbs_g", "Carbohydrates", int(profile.carbs_target_g), int(suggested["carbs_g"])),
        ("fat_g", "Fats", int(profile.fat_target_g), int(suggested["fat_g"])),
        (
            "daily_water_target_ml",
            "Daily Hydration",
            int(profile.daily_water_target_ml),
            int(suggested["daily_water_target_ml"]),
        ),
    ]
    safe_min = int(suggested["safe_minimum_calories"])
    for field, label, actual, rec in checks:
        if rec <= 0:
            continue
        diff_ratio = (actual - rec) / rec
        deviation_pct = round(diff_ratio * 100, 1)
        if field == "calories" and actual < safe_min:
            warnings.append(
                {
                    "field": field,
                    "label": label,
                    "level": "low",
                    "actual": actual,
                    "suggested": rec,
                    "deviation_pct": deviation_pct,
                    "message": (
                        f"This calorie target ({actual} kcal) is below the safe minimum "
                        f"({safe_min} kcal) and may be unsafe."
                    ),
                }
            )
        elif diff_ratio < -0.20:
            warnings.append(
                {
                    "field": field,
                    "label": label,
                    "level": "low",
                    "actual": actual,
                    "suggested": rec,
                    "deviation_pct": deviation_pct,
                    "message": (
                        f"{label} ({actual}) is more than 20% lower than recommended ({rec}) "
                        "and may be unsafe."
                    ),
                }
            )
        elif diff_ratio > 0.20:
            warnings.append(
                {
                    "field": field,
                    "label": label,
                    "level": "high",
                    "actual": actual,
                    "suggested": rec,
                    "deviation_pct": deviation_pct,
                    "message": (
                        f"{label} ({actual}) is more than 20% higher than recommended ({rec}) "
                        "and may be unsafe or counterproductive."
                    ),
                }
            )
    return warnings


def apply_suggested_targets_to_profile(user, profile: FitnessProfile, save: bool = True):
    suggested = calculate_suggested_nutrition_targets(user, profile)
    profile.daily_calorie_target = suggested["calories"]
    profile.protein_target_g = suggested["protein_g"]
    profile.carbs_target_g = suggested["carbs_g"]
    profile.fat_target_g = suggested["fat_g"]
    profile.daily_water_target_ml = suggested["daily_water_target_ml"]
    if save:
        profile.save(
            update_fields=[
                "daily_calorie_target",
                "protein_target_g",
                "carbs_target_g",
                "fat_target_g",
                "daily_water_target_ml",
                "has_custom_targets",
                "updated_at",
            ]
        )
    return suggested


@transaction.atomic
def update_profile(user, data):
    profile = get_profile(user)
    target_fields = {
        "daily_water_target_ml",
        "daily_calorie_target",
        "protein_target_g",
        "carbs_target_g",
        "fat_target_g",
    }
    body_or_goal_fields = {"height_cm", "weight_kg", "age", "sex", "nutrition_goal"}
    all_fields = [
        "experience_level",
        "preferred_units",
        "height_cm",
        "weight_kg",
        "age",
        "sex",
        "nutrition_goal",
        "has_custom_targets",
        "motivation_notifications_enabled",
        "motivation_frequency",
        *target_fields,
    ]
    explicit_targets_provided = any(f in data for f in target_fields)
    body_or_goal_changed = any(
        f in data and getattr(profile, f) != data[f] for f in body_or_goal_fields
    )
    reset_to_suggested = bool(data.get("reset_to_suggested", False))

    for field in all_fields:
        if field in data:
            setattr(profile, field, data[field])

    if reset_to_suggested:
        profile.has_custom_targets = False
        apply_suggested_targets_to_profile(user, profile, save=False)
    elif explicit_targets_provided:
        if "has_custom_targets" not in data:
            profile.has_custom_targets = True
    elif body_or_goal_changed and not profile.has_custom_targets:
        apply_suggested_targets_to_profile(user, profile, save=False)

    profile.save()
    _sync_body_to_member(user, profile)
    return profile


@transaction.atomic
def log_anthropometry(user, data, photo_file=None):
    profile = get_profile(user)
    data = dict(data)
    if "weight_unit" not in data or not data["weight_unit"]:
        data["weight_unit"] = "kg"

    photo_name = None
    if photo_file:
        raw, ext = read_image(photo_file, "check_in_photo")
        photo_name = f"checkins/{secrets.token_hex(16)}.{ext}"
        saved_file = ContentFile(raw)
    else:
        saved_file = None

    waist_cm = data.get("waist_cm")
    waist_inches = data.get("waist_inches")
    if waist_cm is not None and waist_inches is None:
        waist_inches = quantize(Decimal(waist_cm) / CM_PER_INCH)
    elif waist_inches is not None and waist_cm is None:
        waist_cm = quantize(Decimal(waist_inches) * CM_PER_INCH)

    log = AnthropometryLog(
        user=user,
        logged_at=data.get("logged_at", timezone.now()),
        weight=data["weight"],
        weight_unit=data["weight_unit"],
        body_fat_percentage=data.get("body_fat_percentage"),
        waist_inches=waist_inches,
        waist_cm=waist_cm,
    )
    if photo_name and saved_file:
        log.check_in_photo.save(photo_name, saved_file, save=False)
    log.save()

    weight_kg = (
        quantize(Decimal(data["weight"]))
        if data["weight_unit"] == "kg"
        else quantize(Decimal(data["weight"]) / LBS_PER_KG)
    )
    profile.weight_kg = weight_kg
    if not profile.has_custom_targets:
        apply_suggested_targets_to_profile(user, profile, save=False)
    profile.save()
    _sync_body_to_member(user, profile)
    return log


def list_anthropometry(user):
    return AnthropometryLog.objects.filter(user=user).order_by("-logged_at", "-created_at")


def latest_anthropometry(user):
    return list_anthropometry(user).first()
