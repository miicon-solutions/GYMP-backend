import uuid

from django.utils.text import slugify
from rest_framework import serializers

from fitness.serializers import SuggestedTargetsSerializer, TargetWarningSerializer
from nutrition.models import CookingVariation, HydrationLog, MealLog, Recipe
from nutrition.services import accessible_recipes
from workouts.serializers import UserScopedRelatedField


class CookingVariationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CookingVariation
        fields = [
            "id",
            "variation_name",
            "temperature_details",
            "cook_time_minutes",
            "calorie_offset",
            "macro_adjustment",
            "method_notes",
        ]


class RecipeBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recipe
        fields = [
            "id",
            "title",
            "tags",
            "base_calories",
            "base_protein_g",
            "base_carbs_g",
            "base_fat_g",
        ]


class RecipeDetailSerializer(serializers.ModelSerializer):
    cooking_variations = CookingVariationSerializer(many=True, required=False)

    class Meta:
        model = Recipe
        fields = [
            "id",
            "title",
            "slug",
            "is_predefined",
            "base_prep_time_minutes",
            "base_cook_time_minutes",
            "ingredients_json",
            "instructions",
            "tags",
            "base_calories",
            "base_protein_g",
            "base_carbs_g",
            "base_fat_g",
            "cooking_variations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "is_predefined", "created_at", "updated_at"]

    def create(self, validated_data):
        variations_data = validated_data.pop("cooking_variations", None)
        title = validated_data["title"].strip()
        slug = slugify(title)[:180] or "recipe"
        validated_data.setdefault("slug", f"{slug}-{uuid.uuid4().hex[:6]}")
        recipe = super().create(validated_data)
        if variations_data:
            for v_data in variations_data:
                CookingVariation.objects.create(recipe=recipe, **v_data)
        return recipe

    def update(self, instance, validated_data):
        variations_data = validated_data.pop("cooking_variations", None)
        if "title" in validated_data:
            slug = slugify(validated_data["title"])[:180] or "recipe"
            validated_data["slug"] = f"{slug}-{uuid.uuid4().hex[:6]}"
        recipe = super().update(instance, validated_data)
        if variations_data is not None:
            recipe.cooking_variations.all().delete()
            for v_data in variations_data:
                CookingVariation.objects.create(recipe=recipe, **v_data)
        return recipe


class MealLogUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MealLog
        fields = [
            "custom_name",
            "meal_slot",
            "calories",
            "protein_g",
            "carbs_g",
            "fat_g",
            "status",
            "logged_at",
        ]


class MealLogSerializer(serializers.ModelSerializer):
    recipe = RecipeBriefSerializer(read_only=True)
    selected_variation = CookingVariationSerializer(read_only=True)

    class Meta:
        model = MealLog
        fields = [
            "id",
            "logged_at",
            "meal_slot",
            "recipe",
            "selected_variation",
            "custom_name",
            "calories",
            "protein_g",
            "carbs_g",
            "fat_g",
            "status",
        ]
        read_only_fields = ["id"]


class MealLogInputSerializer(serializers.Serializer):
    meal_slot = serializers.ChoiceField(
        choices=["breakfast", "lunch", "dinner", "snack", "workout"], default="lunch"
    )
    recipe_id = UserScopedRelatedField(
        accessible_recipes, source="recipe", required=False, allow_null=True
    )
    selected_variation_id = serializers.PrimaryKeyRelatedField(
        queryset=CookingVariation.objects.all(),
        source="selected_variation",
        required=False,
        allow_null=True,
    )
    custom_name = serializers.CharField(max_length=160, required=False, allow_blank=True)
    calories = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    protein_g = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    carbs_g = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    fat_g = serializers.DecimalField(
        max_digits=6, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    status = serializers.ChoiceField(choices=["planned", "consumed"], default="consumed")
    logged_at = serializers.DateTimeField(required=False)


class MacroStatsSerializer(serializers.Serializer):
    calories = serializers.DecimalField(max_digits=7, decimal_places=2)
    protein_g = serializers.DecimalField(max_digits=6, decimal_places=2)
    carbs_g = serializers.DecimalField(max_digits=6, decimal_places=2)
    fat_g = serializers.DecimalField(max_digits=6, decimal_places=2)


class MacroPercentageSerializer(serializers.Serializer):
    calories = serializers.DecimalField(max_digits=5, decimal_places=1)
    protein_g = serializers.DecimalField(max_digits=5, decimal_places=1)
    carbs_g = serializers.DecimalField(max_digits=5, decimal_places=1)
    fat_g = serializers.DecimalField(max_digits=5, decimal_places=1)


class DailyNutritionSummarySerializer(serializers.Serializer):
    date = serializers.DateField()
    nutrition_goal = serializers.CharField(required=False)
    has_custom_targets = serializers.BooleanField(required=False)
    targets = MacroStatsSerializer()
    suggested_targets = SuggestedTargetsSerializer(required=False)
    warnings = TargetWarningSerializer(many=True, required=False)
    consumed = MacroStatsSerializer()
    remaining = MacroStatsSerializer()
    percentage = MacroPercentageSerializer()
    meals = MealLogSerializer(many=True)
    bangladeshi_foods = serializers.ListField(
        child=serializers.DictField(), required=False
    )


class HydrationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = HydrationLog
        fields = ["id", "date", "intake_amount_ml", "logged_at"]
        read_only_fields = ["id", "date", "logged_at"]


class HydrationSummarySerializer(serializers.Serializer):
    date = serializers.DateField()
    total_intake_ml = serializers.IntegerField()
    target_intake_ml = serializers.IntegerField()
    remaining_ml = serializers.IntegerField()
    quota_progress_percentage = serializers.DecimalField(max_digits=5, decimal_places=1)
    logs = HydrationLogSerializer(many=True)


class HydrationQuickAddInput(serializers.Serializer):
    amount_ml = serializers.IntegerField(default=250, min_value=1, max_value=5000)


class CustomSynthesizerInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    ingredients = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    instructions = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    calories = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=0)
    protein_g = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, default=0)
    carbs_g = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, default=0)
    fat_g = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, default=0)
    prep_time_minutes = serializers.IntegerField(default=5, min_value=0)
    cook_time_minutes = serializers.IntegerField(default=5, min_value=0)
    log_as_meal_today = serializers.BooleanField(default=False)
    meal_slot = serializers.ChoiceField(
        choices=["breakfast", "lunch", "dinner", "snack", "workout"], default="lunch"
    )
