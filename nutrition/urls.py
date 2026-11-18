from django.urls import path

from nutrition.views import (
    ConfirmMealIntakeView,
    CustomSynthesizerView,
    MealLogDetailView,
    MealLogListView,
    QuickAddHydrationView,
    RecipeDetailView,
    RecipeListView,
    TodayHydrationView,
    TodayMealLogsView,
)

urlpatterns = [
    path("recipes/", RecipeListView.as_view(), name="recipe-list"),
    path("recipes/<uuid:pk>/", RecipeDetailView.as_view(), name="recipe-detail"),
    path("logs/", MealLogListView.as_view(), name="nutrition-logs-list"),
    path("logs/<uuid:pk>/", MealLogDetailView.as_view(), name="nutrition-logs-detail"),
    path("logs/today/", TodayMealLogsView.as_view(), name="nutrition-logs-today"),
    path(
        "logs/<uuid:pk>/confirm-intake/",
        ConfirmMealIntakeView.as_view(),
        name="nutrition-logs-confirm",
    ),
    path("hydration/today/", TodayHydrationView.as_view(), name="hydration-today"),
    path("hydration/quick-add/", QuickAddHydrationView.as_view(), name="hydration-quick-add"),
    path(
        "custom-synthesizer/",
        CustomSynthesizerView.as_view(),
        name="custom-synthesizer",
    ),
]
