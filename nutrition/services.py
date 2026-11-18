import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from fitness.services import (
    calculate_suggested_nutrition_targets,
    evaluate_target_warnings,
    get_profile,
)
from nutrition.models import HydrationLog, MealLog, Recipe
from workouts.calculators import quantize

BANGLADESHI_FOOD_CATALOG = [
    {
        "id": "bhaat_white",
        "name": "Steamed White Rice (Bhaat)",
        "name_bn": "সাদা ভাত",
        "category": "carbs",
        "default_grams": 200,
        "per_100g": {"calories": 130, "protein_g": 2.7, "carbs_g": 28.0, "fat_g": 0.3},
    },
    {
        "id": "lal_chal",
        "name": "Brown / Red Rice (Lal Chal Bhaat)",
        "name_bn": "লাল চালের ভাত",
        "category": "carbs",
        "default_grams": 200,
        "per_100g": {"calories": 112, "protein_g": 2.6, "carbs_g": 23.5, "fat_g": 0.9},
    },
    {
        "id": "ata_ruti",
        "name": "Whole Wheat Ata Ruti / Chapati",
        "name_bn": "আটার রুটি",
        "category": "carbs",
        "default_grams": 100,
        "per_100g": {"calories": 264, "protein_g": 9.0, "carbs_g": 51.0, "fat_g": 2.5},
    },
    {
        "id": "masoor_dal",
        "name": "Masoor Dal (Cooked Red Lentils)",
        "name_bn": "মসুর ডাল (রান্না করা)",
        "category": "protein",
        "default_grams": 150,
        "per_100g": {"calories": 116, "protein_g": 9.0, "carbs_g": 20.0, "fat_g": 0.8},
    },
    {
        "id": "moong_dal",
        "name": "Moong Dal (Cooked Yellow Lentils)",
        "name_bn": "মুগ ডাল (রান্না করা)",
        "category": "protein",
        "default_grams": 150,
        "per_100g": {"calories": 105, "protein_g": 7.1, "carbs_g": 19.0, "fat_g": 0.4},
    },
    {
        "id": "deshi_chicken",
        "name": "Chicken Breast / Deshi Murgi (Cooked)",
        "name_bn": "মুরগির মাংস (গ্রিল / সিদ্ধ)",
        "category": "protein",
        "default_grams": 200,
        "per_100g": {"calories": 165, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6},
    },
    {
        "id": "murgir_jhol",
        "name": "Bangladeshi Chicken Curry (Murgir Jhol)",
        "name_bn": "মুরগির ঝোল",
        "category": "protein",
        "default_grams": 200,
        "per_100g": {"calories": 190, "protein_g": 22.0, "carbs_g": 4.0, "fat_g": 9.5},
    },
    {
        "id": "rui_maach",
        "name": "Rohu Fish (Rui Maach Cooked)",
        "name_bn": "রুই মাছ",
        "category": "protein",
        "default_grams": 150,
        "per_100g": {"calories": 120, "protein_g": 19.0, "carbs_g": 0.0, "fat_g": 4.5},
    },
    {
        "id": "tilapia_pangash",
        "name": "Tilapia / Pangash Fish Fillet",
        "name_bn": "তিলাপিয়া / পাঙ্গাশ মাছ",
        "category": "protein",
        "default_grams": 150,
        "per_100g": {"calories": 128, "protein_g": 26.0, "carbs_g": 0.0, "fat_g": 2.7},
    },
    {
        "id": "ilish_maach",
        "name": "Hilsa Fish (Ilish Maach)",
        "name_bn": "ইলিশ মাছ",
        "category": "protein",
        "default_grams": 120,
        "per_100g": {"calories": 273, "protein_g": 21.8, "carbs_g": 0.0, "fat_g": 19.5},
    },
    {
        "id": "gorur_mangsho",
        "name": "Lean Beef Curry (Gorur Mangsho)",
        "name_bn": "গরুর মাংস",
        "category": "protein",
        "default_grams": 150,
        "per_100g": {"calories": 215, "protein_g": 26.0, "carbs_g": 2.0, "fat_g": 11.5},
    },
    {
        "id": "siddho_dim",
        "name": "Boiled Egg (Siddho Dim)",
        "name_bn": "সিদ্ধ ডিম",
        "category": "protein",
        "default_grams": 100,
        "per_100g": {"calories": 155, "protein_g": 13.0, "carbs_g": 1.1, "fat_g": 11.0},
    },
    {
        "id": "dim_bhaji",
        "name": "Egg Omelette (Dim Bhaji)",
        "name_bn": "ডিম ভাজি",
        "category": "protein",
        "default_grams": 100,
        "per_100g": {"calories": 185, "protein_g": 12.5, "carbs_g": 1.5, "fat_g": 14.0},
    },
    {
        "id": "aloo_bharta",
        "name": "Mashed Potato (Aloo Bharta)",
        "name_bn": "আলু ভর্তা",
        "category": "carbs",
        "default_grams": 120,
        "per_100g": {"calories": 115, "protein_g": 2.0, "carbs_g": 21.0, "fat_g": 2.5},
    },
    {
        "id": "shak_bhaji",
        "name": "Leafy Greens (Lal Shak / Palong Shak)",
        "name_bn": "শাক ভাজি (লাল শাক / পালং শাক)",
        "category": "vegetables",
        "default_grams": 150,
        "per_100g": {"calories": 65, "protein_g": 3.2, "carbs_g": 7.0, "fat_g": 2.8},
    },
    {
        "id": "mixed_sabzi",
        "name": "Mixed Vegetable Curry (Sabzi / Labra)",
        "name_bn": "মিক্সড সবজি",
        "category": "vegetables",
        "default_grams": 150,
        "per_100g": {"calories": 80, "protein_g": 2.5, "carbs_g": 11.0, "fat_g": 3.0},
    },
    {
        "id": "chola_boot",
        "name": "Boiled Chickpeas (Chola Boot)",
        "name_bn": "ছোলা বুট",
        "category": "protein",
        "default_grams": 150,
        "per_100g": {"calories": 164, "protein_g": 8.9, "carbs_g": 27.4, "fat_g": 2.6},
    },
    {
        "id": "chira",
        "name": "Flattened Rice (Chira)",
        "name_bn": "চিড়া",
        "category": "carbs",
        "default_grams": 80,
        "per_100g": {"calories": 346, "protein_g": 6.6, "carbs_g": 77.0, "fat_g": 1.2},
    },
    {
        "id": "tok_doi",
        "name": "Sour Yogurt (Tok Doi)",
        "name_bn": "টক দই",
        "category": "protein",
        "default_grams": 150,
        "per_100g": {"calories": 61, "protein_g": 3.5, "carbs_g": 4.7, "fat_g": 3.3},
    },
    {
        "id": "sagor_kola",
        "name": "Banana (Sagor Kola)",
        "name_bn": "সাগর কলা",
        "category": "carbs",
        "default_grams": 120,
        "per_100g": {"calories": 89, "protein_g": 1.1, "carbs_g": 22.8, "fat_g": 0.3},
    },
    {
        "id": "doodh_milk",
        "name": "Liquid Milk (Gorur Doodh)",
        "name_bn": "গরুর দুধ",
        "category": "protein",
        "default_grams": 250,
        "per_100g": {"calories": 62, "protein_g": 3.3, "carbs_g": 4.8, "fat_g": 3.3},
    },
]


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

    suggested = calculate_suggested_nutrition_targets(user, profile)
    warnings = evaluate_target_warnings(profile, suggested)

    return {
        "date": target_date,
        "nutrition_goal": profile.nutrition_goal,
        "has_custom_targets": profile.has_custom_targets,
        "targets": {
            "calories": target_cals,
            "protein_g": target_prot,
            "carbs_g": target_carbs,
            "fat_g": target_fat,
        },
        "suggested_targets": suggested,
        "warnings": warnings,
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
        "bangladeshi_foods": BANGLADESHI_FOOD_CATALOG,
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
    raw_tags = list(data.get("tags") or ["Custom"])
    if "Meal Preset" not in raw_tags:
        raw_tags.append("Meal Preset")
    recipe = Recipe.objects.create(
        title=title,
        slug=unique_slug,
        is_predefined=False,
        created_by=user,
        base_prep_time_minutes=data.get("prep_time_minutes", 5),
        base_cook_time_minutes=data.get("cook_time_minutes", 5),
        ingredients_json=data.get("ingredients", []),
        instructions=data.get("instructions", []),
        tags=raw_tags,
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
