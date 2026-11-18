from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from fitness.models import (
    WEIGHT_UNITS,
    AnthropometryLog,
    Article,
    FitnessProfile,
    SavedArticle,
)


class FitnessProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FitnessProfile
        fields = [
            "experience_level",
            "preferred_units",
            "daily_water_target_ml",
            "daily_calorie_target",
            "protein_target_g",
            "carbs_target_g",
            "fat_target_g",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class AnthropometryLogSerializer(serializers.ModelSerializer):
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = AnthropometryLog
        fields = [
            "id",
            "logged_at",
            "weight",
            "weight_unit",
            "body_fat_percentage",
            "waist_inches",
            "photo_url",
            "created_at",
        ]
        read_only_fields = ["id", "photo_url", "created_at"]

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

