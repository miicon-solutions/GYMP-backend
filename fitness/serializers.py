from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from fitness.models import (
    MOTIVATION_FREQUENCIES,
    NUTRITION_GOALS,
    SEX_CHOICES,
    WEIGHT_UNITS,
    AnthropometryLog,
    Article,
    FitnessProfile,
    SavedArticle,
)
from fitness.services import calculate_suggested_nutrition_targets, evaluate_target_warnings


class SuggestedTargetsSerializer(serializers.Serializer):
    goal = serializers.CharField()
    calories = serializers.IntegerField()
    protein_g = serializers.IntegerField()
    carbs_g = serializers.IntegerField()
    fat_g = serializers.IntegerField()
    daily_water_target_ml = serializers.IntegerField()
    safe_minimum_calories = serializers.IntegerField()
    has_body_data = serializers.BooleanField()
    weight_kg = serializers.FloatField()
    height_cm = serializers.FloatField()
    age = serializers.IntegerField()
    sex = serializers.CharField()


class TargetWarningSerializer(serializers.Serializer):
    field = serializers.CharField()
    label = serializers.CharField()
    level = serializers.CharField()
    actual = serializers.IntegerField()
    suggested = serializers.IntegerField()
    deviation_pct = serializers.FloatField()
    message = serializers.CharField()


class FitnessProfileSerializer(serializers.ModelSerializer):
    reset_to_suggested = serializers.BooleanField(write_only=True, required=False, default=False)
    suggested_targets = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = FitnessProfile
        fields = [
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
            "daily_water_target_ml",
            "daily_calorie_target",
            "protein_target_g",
            "carbs_target_g",
            "fat_target_g",
            "reset_to_suggested",
            "suggested_targets",
            "warnings",
            "updated_at",
        ]
        read_only_fields = ["suggested_targets", "warnings", "updated_at"]
        extra_kwargs = {
            "sex": {"choices": SEX_CHOICES, "required": False, "allow_blank": True},
            "nutrition_goal": {"choices": NUTRITION_GOALS, "required": False},
            "motivation_frequency": {"choices": MOTIVATION_FREQUENCIES, "required": False},
        }

    @extend_schema_field(SuggestedTargetsSerializer)
    def get_suggested_targets(self, obj):
        return calculate_suggested_nutrition_targets(obj.user, obj)

    @extend_schema_field(TargetWarningSerializer(many=True))
    def get_warnings(self, obj):
        suggested = calculate_suggested_nutrition_targets(obj.user, obj)
        return evaluate_target_warnings(obj, suggested)


class AnthropometryLogSerializer(serializers.ModelSerializer):
    photo_url = serializers.SerializerMethodField()
    weight_kg = serializers.SerializerMethodField()

    class Meta:
        model = AnthropometryLog
        fields = [
            "id",
            "logged_at",
            "weight",
            "weight_unit",
            "weight_kg",
            "body_fat_percentage",
            "waist_inches",
            "waist_cm",
            "photo_url",
            "created_at",
        ]
        read_only_fields = ["id", "weight_kg", "photo_url", "created_at"]

    @extend_schema_field(serializers.DecimalField(max_digits=6, decimal_places=2))
    def get_weight_kg(self, obj):
        from decimal import Decimal

        from workouts.calculators import LBS_PER_KG, quantize

        if obj.weight_unit == "kg":
            return quantize(obj.weight)
        return quantize(Decimal(obj.weight) / LBS_PER_KG)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_photo_url(self, obj):
        if not obj.check_in_photo:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.check_in_photo.url)
        return obj.check_in_photo.url


class AnthropometryInputSerializer(serializers.Serializer):
    weight = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=1, max_value=1500)
    weight_unit = serializers.ChoiceField(choices=WEIGHT_UNITS, required=False)
    body_fat_percentage = serializers.DecimalField(
        max_digits=4, decimal_places=1, min_value=1, max_value=75, required=False, allow_null=True
    )
    waist_inches = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=10, max_value=120, required=False, allow_null=True
    )
    waist_cm = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=25, max_value=300, required=False, allow_null=True
    )
    logged_at = serializers.DateTimeField(required=False)
    check_in_photo = serializers.ImageField(required=False, allow_null=True)


class ArticleSerializer(serializers.ModelSerializer):
    is_saved = serializers.SerializerMethodField()
    saves_count = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "id",
            "title",
            "url",
            "excerpt",
            "source",
            "category",
            "tags",
            "reading_time_minutes",
            "cover_image_url",
            "is_pinned",
            "is_saved",
            "saves_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_saved", "saves_count", "created_at", "updated_at"]

    @extend_schema_field(serializers.BooleanField())
    def get_is_saved(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        if hasattr(obj, "user_has_saved"):
            return bool(obj.user_has_saved)
        return SavedArticle.objects.filter(user=request.user, article=obj).exists()

    @extend_schema_field(serializers.IntegerField())
    def get_saves_count(self, obj):
        if hasattr(obj, "total_saves"):
            return obj.total_saves
        return obj.saved_by.count()


class ArticleInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = [
            "id",
            "title",
            "url",
            "excerpt",
            "source",
            "category",
            "tags",
            "reading_time_minutes",
            "cover_image_url",
            "is_pinned",
        ]
        read_only_fields = ["id"]


class SavedArticleSerializer(serializers.ModelSerializer):
    article = ArticleSerializer(read_only=True)

    class Meta:
        model = SavedArticle
        fields = ["id", "article", "saved_at", "is_read"]
        read_only_fields = ["id", "article", "saved_at"]


class SaveArticleOutputSerializer(serializers.Serializer):
    is_saved = serializers.BooleanField()
    article_id = serializers.UUIDField()
    message = serializers.CharField()

