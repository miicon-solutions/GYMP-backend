from django.urls import path
from rest_framework.routers import SimpleRouter

from workouts.views import (
    ExerciseAnalyticsView,
    ExerciseViewSet,
    OverallAnalyticsView,
    RoutineViewSet,
    WorkoutSessionViewSet,
)

router = SimpleRouter()
router.register("exercises", ExerciseViewSet, basename="exercise")
router.register("routines", RoutineViewSet, basename="routine")
router.register("sessions", WorkoutSessionViewSet, basename="workout-session")

urlpatterns = [
    path("analytics/overall/", OverallAnalyticsView.as_view()),
    path("analytics/exercise/<uuid:exercise_id>/", ExerciseAnalyticsView.as_view()),
    *router.urls,
]
