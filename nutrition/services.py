from decimal import Decimal
import uuid

from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from fitness.services import get_profile
from nutrition.models import HydrationLog, MealLog, Recipe
from workouts.calculators import quantize


def accessible_recipes(user):
    return Recipe.objects.filter(Q(is_predefined=True) | Q(created_by=user))


def get_recipe(user, pk):
    return get_object_or_404(accessible_recipes(user).prefetch_related("cooking_variations"), pk=pk)


def calculate_variation_macros(recipe, variation=None):
    cals = Decimal(str(recipe.base_calories))
    prot = Decimal(str(recipe.base_protein_g))
    carbs = Decimal(str(recipe.base_carbs_g))
    fat = Decimal(str(recipe.base_fat_g))

    if variation:
        cals += Decimal(str(variation.calorie_offset))
        adj = variation.macro_adjustment or {}
        prot += Decimal(str(adj.get("protein_g", 0)))
        carbs += Decimal(str(adj.get("carbs_g", 0)))
        fat += Decimal(str(adj.get("fat_g", 0)))

    return {
        "calories": max(Decimal(0), quantize(cals)),
        "protein_g": max(Decimal(0), quantize(prot)),
        "carbs_g": max(Decimal(0), quantize(carbs)),
        "fat_g": max(Decimal(0), quantize(fat)),
    }


@transaction.atomic
def log_meal(user, data):
    data = dict(data)
    recipe = data.get("recipe")
    variation = data.get("selected_variation")

    if variation and recipe and variation.recipe_id != recipe.id:
        raise ValidationError({"selected_variation": "Variation belongs to a different recipe."})

    calculated = None
    if recipe:
        calculated = calculate_variation_macros(recipe, variation)

    calories = data.get("calories")
    if calories is None:
        if calculated:
            calories = calculated["calories"]
        else:
            raise ValidationError({"calories": "Calories are required for custom meals."})

    protein_g = data.get("protein_g")
    if protein_g is None:
        protein_g = calculated["protein_g"] if calculated else Decimal(0)

    carbs_g = data.get("carbs_g")
    if carbs_g is None:
        carbs_g = calculated["carbs_g"] if calculated else Decimal(0)

    fat_g = data.get("fat_g")
    if fat_g is None:
        fat_g = calculated["fat_g"] if calculated else Decimal(0)

    custom_name = data.get("custom_name", "")
    if not custom_name and recipe:
        custom_name = recipe.title
        if variation:
            custom_name += f" ({variation.variation_name})"

    meal = MealLog.objects.create(
        user=user,
        logged_at=data.get("logged_at", timezone.now()),
        meal_slot=data.get("meal_slot", "lunch"),
        recipe=recipe,
        selected_variation=variation,
        custom_name=custom_name,
        calories=quantize(calories),
        protein_g=quantize(protein_g),
        carbs_g=quantize(carbs_g),
        fat_g=quantize(fat_g),
        status=data.get("status", "consumed"),
    )
    return meal


@transaction.atomic
def confirm_intake(user, log_id):
    meal = get_object_or_404(MealLog.objects.select_for_update(), pk=log_id, user=user)
    meal.status = "consumed"
    meal.save(update_fields=["status", "updated_at"])
    return meal


def today_nutrition(user, target_date=None):
    target_date = target_date or timezone.localdate()
    profile = get_profile(user)

    meals = (
        MealLog.objects.filter(user=user, logged_at__date=target_date)
        .select_related("recipe", "selected_variation")
        .order_by("logged_at")
    )

    consumed = meals.filter(status="consumed").aggregate(
        cals=Sum("calories"),
        prot=Sum("protein_g"),
        carbs=Sum("carbs_g"),
        fat=Sum("fat_g"),
    )

    logged_cals = quantize(consumed["cals"] or 0)
    logged_prot = quantize(consumed["prot"] or 0)
    logged_carbs = quantize(consumed["carbs"] or 0)
    logged_fat = quantize(consumed["fat"] or 0)

    target_cals = Decimal(str(profile.daily_calorie_target))
    target_prot = Decimal(str(profile.protein_target_g))
    target_carbs = Decimal(str(profile.carbs_target_g))
    target_fat = Decimal(str(profile.fat_target_g))

    return {
        "date": target_date,
        "targets": {
            "calories": target_cals,
            "protein_g": target_prot,
            "carbs_g": target_carbs,
            "fat_g": target_fat,
        },
        "consumed": {
            "calories": logged_cals,
            "protein_g": logged_prot,
            "carbs_g": logged_carbs,
            "fat_g": logged_fat,
        },
        "remaining": {
            "calories": max(Decimal(0), target_cals - logged_cals),
            "protein_g": max(Decimal(0), target_prot - logged_prot),
            "carbs_g": max(Decimal(0), target_carbs - logged_carbs),
            "fat_g": max(Decimal(0), target_fat - logged_fat),
        },
        "percentage": {
            "calories": quantize((logged_cals / target_cals * 100) if target_cals else 0, "0.1"),
            "protein_g": quantize((logged_prot / target_prot * 100) if target_prot else 0, "0.1"),
            "carbs_g": quantize((logged_carbs / target_carbs * 100) if target_carbs else 0, "0.1"),
            "fat_g": quantize((logged_fat / target_fat * 100) if target_fat else 0, "0.1"),
        },
        "meals": meals,
    }


def today_hydration(user, target_date=None):
    target_date = target_date or timezone.localdate()
    profile = get_profile(user)

    logs = HydrationLog.objects.filter(user=user, date=target_date).order_by("-logged_at")
    total_ml = logs.aggregate(total=Sum("intake_amount_ml"))["total"] or 0
    target_ml = profile.daily_water_target_ml

    return {
        "date": target_date,
        "total_intake_ml": total_ml,
        "target_intake_ml": target_ml,
        "remaining_ml": max(0, target_ml - total_ml),
        "quota_progress_percentage": quantize(
            (total_ml / target_ml * 100) if target_ml else 0, "0.1"
        ),
        "logs": logs,
    }


@transaction.atomic
def quick_add_hydration(user, amount_ml, target_date=None):
    target_date = target_date or timezone.localdate()
    if amount_ml <= 0 or amount_ml > 5000:
        raise ValidationError({"amount_ml": "Amount must be between 1 and 5000 ml."})

    HydrationLog.objects.create(
        user=user,
        date=target_date,
        intake_amount_ml=amount_ml,
        logged_at=timezone.now(),
    )
    return today_hydration(user, target_date)


@transaction.atomic
def save_custom_synthesizer(user, data):
    title = data["title"].strip()
    base_slug = slugify(title)[:150] or "custom-meal"
    unique_slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"
    recipe = Recipe.objects.create(
        title=title,
        slug=unique_slug,
        is_predefined=False,
        created_by=user,
        base_prep_time_minutes=data.get("prep_time_minutes", 5),
        base_cook_time_minutes=data.get("cook_time_minutes", 5),
        ingredients_json=data.get("ingredients", []),
        instructions=data.get("instructions", []),
        tags=data.get("tags", ["Custom"]),
        base_calories=quantize(data["calories"]),
        base_protein_g=quantize(data.get("protein_g", 0)),
        base_carbs_g=quantize(data.get("carbs_g", 0)),
        base_fat_g=quantize(data.get("fat_g", 0)),
    )
    if data.get("log_as_meal_today", False):
        log_meal(
            user,
            {
                "recipe": recipe,
                "meal_slot": data.get("meal_slot", "lunch"),
                "custom_name": title,
                "calories": recipe.base_calories,
                "protein_g": recipe.base_protein_g,
                "carbs_g": recipe.base_carbs_g,
                "fat_g": recipe.base_fat_g,
                "status": "consumed",
            },
        )
    return recipe
