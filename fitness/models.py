from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import Entity

EXPERIENCE_LEVELS = [
    ("beginner", "Beginner"),
    ("intermediate", "Intermediate"),
    ("advanced", "Advanced"),
    ("elite", "Elite"),
]
UNIT_SYSTEMS = [("metric", "Metric (kg/cm)"), ("imperial", "Imperial (lbs/in)")]
WEIGHT_UNITS = [("kg", "Kilograms"), ("lbs", "Pounds")]


class FitnessProfile(Entity):
    """Training and nutrition preferences; created lazily for every member."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fitness_profile"
    )
    experience_level = models.CharField(
        max_length=12, choices=EXPERIENCE_LEVELS, default="beginner"
    )
    preferred_units = models.CharField(max_length=8, choices=UNIT_SYSTEMS, default="metric")
    daily_water_target_ml = models.PositiveIntegerField(
        default=3500, validators=[MinValueValidator(500), MaxValueValidator(10000)]
    )
    daily_calorie_target = models.PositiveIntegerField(
        default=2500, validators=[MinValueValidator(800), MaxValueValidator(10000)]
    )
    protein_target_g = models.PositiveIntegerField(
        default=150, validators=[MaxValueValidator(1000)]
    )
    carbs_target_g = models.PositiveIntegerField(default=250, validators=[MaxValueValidator(1500)])
    fat_target_g = models.PositiveIntegerField(default=70, validators=[MaxValueValidator(500)])

    @property
    def weight_unit(self):
        return "lbs" if self.preferred_units == "imperial" else "kg"

    def __str__(self):
        return f"Fitness profile for {self.user_id}"


class AnthropometryLog(Entity):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="anthropometry_logs"
    )
    logged_at = models.DateTimeField(default=timezone.now)
    weight = models.DecimalField(max_digits=6, decimal_places=2)
    weight_unit = models.CharField(max_length=3, choices=WEIGHT_UNITS, default="kg")
    body_fat_percentage = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    waist_inches = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # Private body photos live under checkins/ and are only served to their owner.
    check_in_photo = models.ImageField(blank=True, null=True)

    class Meta(Entity.Meta):
        indexes = [models.Index(fields=["user", "-logged_at"], name="anthro_user_logged")]
        constraints = [
            models.CheckConstraint(condition=models.Q(weight__gt=0), name="anthro_positive_weight"),
            models.CheckConstraint(
                condition=models.Q(body_fat_percentage__isnull=True)
                | models.Q(body_fat_percentage__gte=1, body_fat_percentage__lte=75),
                name="anthro_body_fat_range",
            ),
        ]

    def __str__(self):
        return f"{self.weight} {self.weight_unit} @ {self.logged_at:%Y-%m-%d}"


ARTICLE_CATEGORIES = [
    ("training", "Training & Hypertrophy"),
    ("nutrition", "Nutrition & Diet"),
    ("recovery", "Recovery & Sleep"),
    ("injury_prevention", "Injury Prevention & Form"),
    ("science", "Sports Science & Research"),
    ("lifestyle", "Gym Lifestyle & Motivation"),
]


class Article(Entity):
    """Educational fitness articles curated by gym staff and coaches."""

    title = models.CharField(max_length=255)
    url = models.URLField(max_length=1000)
    excerpt = models.TextField(blank=True, default="")
    source = models.CharField(max_length=120, blank=True, default="")
    category = models.CharField(max_length=30, choices=ARTICLE_CATEGORIES, default="training")
    tags = models.JSONField(default=list, blank=True)
    reading_time_minutes = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(180)]
    )
    cover_image_url = models.URLField(max_length=1000, blank=True, default="")
    is_pinned = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_articles",
    )

    class Meta(Entity.Meta):
        ordering = ["-is_pinned", "-created_at"]
        indexes = [
            models.Index(fields=["category", "-created_at"], name="article_cat_idx"),
            models.Index(fields=["-is_pinned", "-created_at"], name="article_pinned_idx"),
        ]

    def __str__(self):
        return self.title


class SavedArticle(Entity):
    """Personal bookmark of articles saved by members to read later."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_articles"
    )
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="saved_by")
    saved_at = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    class Meta(Entity.Meta):
        unique_together = [("user", "article")]
        ordering = ["-saved_at"]
        indexes = [
            models.Index(fields=["user", "-saved_at"], name="saved_article_user_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} saved {self.article_id}"

