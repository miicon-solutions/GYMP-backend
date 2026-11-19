from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import Entity

MEAL_SLOTS = [
    ("breakfast", "Breakfast"),
    ("lunch", "Lunch"),
    ("dinner", "Dinner"),
    ("snack", "Snack"),
    ("workout", "Intra/Post Workout"),
]
MEAL_STATUSES = [
    ("planned", "Planned"),
    ("consumed", "Consumed"),
]


class Recipe(Entity):
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180)
    is_predefined = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="custom_recipes",
    )
    base_prep_time_minutes = models.PositiveSmallIntegerField(default=10)
    base_cook_time_minutes = models.PositiveSmallIntegerField(default=20)
    ingredients_json = models.JSONField(
        default=list,
        help_text='List of items e.g. [{"name": "Chicken Breast", "amount": "220g", "protein": 36}]',
    )
    instructions = models.JSONField(default=list, help_text="List of step protocols")
    tags = models.JSONField(default=list, blank=True, help_text='["Hypertrophy", "High Protein"]')
    base_calories = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    base_protein_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    base_carbs_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    base_fat_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta(Entity.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["title"], condition=Q(created_by__isnull=True), name="system_recipe_title"
            ),
            models.CheckConstraint(
                condition=Q(is_predefined=True, created_by__isnull=True)
                | Q(is_predefined=False, created_by__isnull=False),
                name="recipe_predefined_ownership",
            ),
        ]

    def __str__(self):
        return self.title


class CookingVariation(Entity):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="cooking_variations")
    variation_name = models.CharField(max_length=120)
    temperature_details = models.CharField(max_length=80, blank=True)
    cook_time_minutes = models.PositiveSmallIntegerField(default=15)
    calorie_offset = models.IntegerField(default=0, help_text="e.g. +35 for air fryer oil spray")
    macro_adjustment = models.JSONField(
        default=dict, blank=True, help_text='{"protein_g": 0, "carbs_g": 0, "fat_g": 4}'
    )
    method_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["variation_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "variation_name"], name="unique_recipe_variation"
            )
        ]

    def __str__(self):
        return f"{self.recipe.title} - {self.variation_name}"


class MealLog(Entity):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meal_logs"
    )
    logged_at = models.DateTimeField(default=timezone.now)
    meal_slot = models.CharField(max_length=12, choices=MEAL_SLOTS, default="lunch")
    recipe = models.ForeignKey(
        Recipe, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs"
    )
    selected_variation = models.ForeignKey(
        CookingVariation, on_delete=models.SET_NULL, null=True, blank=True, related_name="logs"
    )
    custom_name = models.CharField(max_length=160, blank=True)
    calories = models.DecimalField(max_digits=7, decimal_places=2)
    protein_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    carbs_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    fat_g = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    status = models.CharField(max_length=12, choices=MEAL_STATUSES, default="consumed")

    class Meta(Entity.Meta):
        indexes = [models.Index(fields=["user", "-logged_at"], name="meal_user_logged")]

    def __str__(self):
        name = self.custom_name or (self.recipe.title if self.recipe else "Quick Meal")
        return f"{self.user_id} - {name} ({self.calories} kcal)"


class HydrationLog(Entity):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hydration_logs"
    )
    date = models.DateField(default=timezone.localdate)
    intake_amount_ml = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(15000)]
    )
    logged_at = models.DateTimeField(default=timezone.now)

    class Meta(Entity.Meta):
        indexes = [models.Index(fields=["user", "date"], name="hydration_user_date")]

    def __str__(self):
        return f"{self.user_id} - {self.date}: {self.intake_amount_ml}ml"
