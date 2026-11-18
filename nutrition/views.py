from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import ordered_pagination
from nutrition import services
from nutrition.filters import RecipeFilter
from nutrition.models import MealLog, Recipe
from nutrition.serializers import (
    CustomSynthesizerInputSerializer,
    DailyNutritionSummarySerializer,
    HydrationQuickAddInput,
    HydrationSummarySerializer,
    MealLogInputSerializer,
    MealLogSerializer,
    MealLogUpdateSerializer,
    RecipeDetailSerializer,
)


class RecipeListView(generics.ListCreateAPIView):
    """List predefined and user-created custom recipes. Staff can add new system or custom recipes."""

    permission_classes = [IsAuthenticated]
    serializer_class = RecipeDetailSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = RecipeFilter
    search_fields = ["title", "instructions"]
    ordering_fields = ["title", "base_calories", "base_protein_g", "created_at"]
    ordering = ["title"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Recipe.objects.none()
        if self.request.user.role == "admin":
            return Recipe.objects.all().prefetch_related("cooking_variations")
        return services.accessible_recipes(self.request.user).prefetch_related("cooking_variations")

    def perform_create(self, serializer):
        if self.request.user.role == "admin":
            is_predefined = self.request.data.get("is_predefined", True)
            serializer.save(
                is_predefined=is_predefined,
                created_by=None if is_predefined else self.request.user,
            )
        else:
            serializer.save(
                is_predefined=False,
                created_by=self.request.user,
            )


class RecipeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, edit, or delete full recipe details. Staff can manage all recipes."""

    permission_classes = [IsAuthenticated]
    serializer_class = RecipeDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Recipe.objects.none()
        if self.request.user.role == "admin":
            return Recipe.objects.all().prefetch_related("cooking_variations")
        return services.accessible_recipes(self.request.user).prefetch_related("cooking_variations")

    def perform_update(self, serializer):
        recipe = self.get_object()
        if self.request.user.role != "admin" and recipe.created_by_id != self.request.user.id:
            raise PermissionDenied("You can only edit your own custom recipes.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role != "admin" and instance.created_by_id != self.request.user.id:
            raise PermissionDenied("You can only delete your own custom recipes.")
        instance.delete()


class MealLogListView(generics.ListCreateAPIView):
    """List or log meal entries. Staff can view all members' meal logs and log meals for members."""

    permission_classes = [IsAuthenticated]
    serializer_class = MealLogSerializer
    pagination_class = ordered_pagination("-logged_at", "-created_at", "-id")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MealLog.objects.none()
        user = self.request.user
        if user.role == "admin":
            qs = MealLog.objects.all().select_related("recipe", "selected_variation")
            user_id = self.request.query_params.get("user_id")
            if user_id:
                qs = qs.filter(user_id=user_id)
        else:
            qs = MealLog.objects.filter(user=user).select_related("recipe", "selected_variation")
        slot = self.request.query_params.get("meal_slot")
        if slot:
            qs = qs.filter(meal_slot=slot)
        date = self.request.query_params.get("date")
        if date:
            qs = qs.filter(logged_at__date=date)
        return qs

    def get_serializer_class(self):
        if self.request.method == "POST":
            return MealLogInputSerializer
        return MealLogSerializer

    def perform_create(self, serializer):
        target_user = self.request.user
        if self.request.user.role == "admin" and self.request.data.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=self.request.data["user_id"])
        serializer.instance = services.log_meal(target_user, serializer.validated_data)


class MealLogDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a specific meal log. Staff can manage any meal log."""

    permission_classes = [IsAuthenticated]
    serializer_class = MealLogSerializer

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return MealLogUpdateSerializer
        return MealLogSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MealLog.objects.none()
        if self.request.user.role == "admin":
            return MealLog.objects.all().select_related("recipe", "selected_variation")
        return MealLog.objects.filter(user=self.request.user).select_related(
            "recipe", "selected_variation"
        )

    def perform_update(self, serializer):
        meal = self.get_object()
        if self.request.user.role != "admin" and meal.user_id != self.request.user.id:
            raise PermissionDenied("You can only edit your own meal logs.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role != "admin" and instance.user_id != self.request.user.id:
            raise PermissionDenied("You can only delete your own meal logs.")
        instance.delete()


class TodayMealLogsView(generics.GenericAPIView):
    """Daily nutrition summary (targets vs logged calories/macros) and meal logger."""

    permission_classes = [IsAuthenticated]
    serializer_class = DailyNutritionSummarySerializer

    @extend_schema(responses=DailyNutritionSummarySerializer)
    def get(self, request):
        target_user = request.user
        if request.user.role == "admin" and request.query_params.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=request.query_params["user_id"])
        summary = services.today_nutrition(target_user)
        return Response(DailyNutritionSummarySerializer(summary).data)

    @extend_schema(request=MealLogInputSerializer, responses={201: MealLogSerializer})
    def post(self, request):
        target_user = request.user
        if request.user.role == "admin" and request.data.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=request.data["user_id"])
        serializer = MealLogInputSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        meal = services.log_meal(target_user, serializer.validated_data)
        return Response(MealLogSerializer(meal).data, status=status.HTTP_201_CREATED)


class ConfirmMealIntakeView(generics.GenericAPIView):
    """Confirm consumption of a planned meal log."""

    permission_classes = [IsAuthenticated]
    serializer_class = MealLogSerializer

    @extend_schema(request=None, responses=MealLogSerializer)
    def patch(self, request, pk):
        meal_obj = get_object_or_404(MealLog, pk=pk)
        if request.user.role != "admin" and meal_obj.user_id != request.user.id:
            raise PermissionDenied("You can only confirm intake for your own meals.")
        meal = services.confirm_intake(meal_obj.user, pk)
        return Response(MealLogSerializer(meal).data)


class TodayHydrationView(generics.GenericAPIView):
    """Retrieve today's hydration intake and quota progress."""

    permission_classes = [IsAuthenticated]
    serializer_class = HydrationSummarySerializer

    @extend_schema(responses=HydrationSummarySerializer)
    def get(self, request):
        target_user = request.user
        if request.user.role == "admin" and request.query_params.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=request.query_params["user_id"])
        summary = services.today_hydration(target_user)
        return Response(HydrationSummarySerializer(summary).data)


class QuickAddHydrationView(generics.GenericAPIView):
    """Quick-tap water intake logger (e.g. +250ml, +500ml)."""

    permission_classes = [IsAuthenticated]
    serializer_class = HydrationQuickAddInput

    @extend_schema(request=HydrationQuickAddInput, responses={201: HydrationSummarySerializer})
    def post(self, request):
        target_user = request.user
        if request.user.role == "admin" and request.data.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=request.data["user_id"])
        serializer = HydrationQuickAddInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary = services.quick_add_hydration(target_user, serializer.validated_data["amount_ml"])
        return Response(HydrationSummarySerializer(summary).data, status=status.HTTP_201_CREATED)
        serializer = HydrationQuickAddInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.quick_add_hydration(
            request.user, amount_ml=serializer.validated_data["amount_ml"]
        )
        return Response(HydrationSummarySerializer(updated).data, status=status.HTTP_201_CREATED)


class CustomSynthesizerView(generics.GenericAPIView):
    """Save custom macro/meal formulation synthesized from raw ingredients."""

    permission_classes = [IsAuthenticated]
    serializer_class = CustomSynthesizerInputSerializer

    @extend_schema(request=CustomSynthesizerInputSerializer, responses={201: RecipeDetailSerializer})
    def post(self, request):
        serializer = CustomSynthesizerInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recipe = services.save_custom_synthesizer(request.user, serializer.validated_data)
        return Response(RecipeDetailSerializer(recipe).data, status=status.HTTP_201_CREATED)
