from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core.api import StaffOrMember, ordered_pagination
from workouts import services
from workouts.filters import ExerciseFilter, RoutineFilter, SessionFilter
from workouts.models import Exercise, Routine, RoutineExercise, WorkoutSession, WorkoutSet
from workouts.serializers import (
    AnalyticsOutput,
    AnalyticsQuery,
    CompleteSessionInput,
    ExerciseSerializer,
    LogSetInput,
    LogSetOutput,
    RoutineSerializer,
    StartSessionInput,
    WorkoutSessionListSerializer,
    WorkoutSessionSerializer,
    WorkoutSessionUpdateSerializer,
)

OWNER_WRITE_ACTIONS = {"update", "partial_update", "destroy"}


class MemberScopedMixin:
    permission_classes = [StaffOrMember]
    lookup_value_regex = "[0-9a-f-]{36}"

    def schema_safe(self, queryset_factory, empty):
        if getattr(self, "swagger_fake_view", False):
            return empty.objects.none()
        return queryset_factory(self.request.user)


class ExerciseViewSet(MemberScopedMixin, viewsets.ModelViewSet):
    """System exercises plus custom exercises. Staff can create, edit, or delete any exercise."""

    serializer_class = ExerciseSerializer
    http_method_names = ["get", "post", "patch", "delete"]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ExerciseFilter
    search_fields = ["name", "target_vector"]
    ordering_fields = ["name", "muscle_group", "category", "created_at"]
    ordering = ["name"]

    def get_queryset(self):
        user = self.request.user
        if getattr(self, "swagger_fake_view", False):
            return Exercise.objects.none()
        if user.role == "admin":
            return Exercise.objects.all()
        if self.action in OWNER_WRITE_ACTIONS:
            return Exercise.objects.filter(created_by=user)
        return services.accessible_exercises(user)

    def perform_create(self, serializer):
        if self.request.user.role == "admin":
            is_custom = self.request.data.get("is_custom", False)
            serializer.save(
                created_by=self.request.user if is_custom else None,
                is_custom=is_custom,
            )
        else:
            serializer.save(created_by=self.request.user, is_custom=True)


class RoutineViewSet(MemberScopedMixin, viewsets.ModelViewSet):
    """Predefined protocols and custom routines. Staff can manage all routines."""

    serializer_class = RoutineSerializer
    http_method_names = ["get", "post", "patch", "delete"]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = RoutineFilter
    search_fields = ["title", "description"]
    ordering_fields = ["title", "estimated_duration_minutes", "created_at"]
    ordering = ["title"]

    def get_queryset(self):
        user = self.request.user
        if getattr(self, "swagger_fake_view", False):
            return Routine.objects.none()
        if user.role == "admin":
            rows = Routine.objects.all()
        elif self.action in OWNER_WRITE_ACTIONS:
            rows = Routine.objects.filter(created_by=user)
        else:
            rows = services.accessible_routines(user)
        return rows.prefetch_related(
            Prefetch("items", RoutineExercise.objects.select_related("exercise"))
        )

    def perform_create(self, serializer):
        if self.request.user.role == "admin":
            is_predefined = self.request.data.get("is_predefined", True)
            serializer.save(
                created_by=None if is_predefined else self.request.user,
                is_predefined=is_predefined,
            )
        else:
            serializer.save(created_by=self.request.user, is_predefined=False)


class WorkoutSessionViewSet(
    MemberScopedMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """Workout history and live session engine. Staff can view, edit, delete, and manage sessions."""

    http_method_names = ["get", "post", "patch", "put", "delete", "head", "options"]
    filter_backends = [DjangoFilterBackend]
    filterset_class = SessionFilter
    pagination_class = ordered_pagination("-start_time", "-id")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WorkoutSession.objects.none()
        user = self.request.user
        if user.role == "admin":
            rows = WorkoutSession.objects.all().select_related("routine")
            user_id = self.request.query_params.get("user_id")
            if user_id:
                rows = rows.filter(user_id=user_id)
        else:
            rows = services.session_queryset(user)
        if self.action == "list":
            return rows.annotate(
                set_count=Count("sets"), pr_count=Count("sets", filter=Q(sets__is_pr=True))
            )
        return rows.prefetch_related(
            Prefetch("sets", WorkoutSet.objects.select_related("exercise"))
        )

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return WorkoutSessionUpdateSerializer
        return WorkoutSessionListSerializer if self.action == "list" else WorkoutSessionSerializer

    def _detail(self, session, code=status.HTTP_200_OK):
        return Response(WorkoutSessionSerializer(self.get_queryset().get(pk=session.pk)).data, code)

    @extend_schema(request=StartSessionInput, responses={201: WorkoutSessionSerializer})
    @action(detail=False, methods=["post"])
    def start(self, request):
        data = StartSessionInput(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        target_user = request.user
        if request.user.role == "admin" and request.data.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=request.data["user_id"])
        session = services.start_session(target_user, data.validated_data)
        return self._detail(session, status.HTTP_201_CREATED)

    @extend_schema(responses=WorkoutSessionSerializer)
    @action(detail=False, methods=["get"])
    def active(self, request):
        session = self.get_queryset().filter(status="in_progress").first()
        if not session:
            return Response({"detail": "No workout in progress."}, status=404)
        return Response(WorkoutSessionSerializer(session).data)

    @extend_schema(request=LogSetInput, responses={201: LogSetOutput})
    @action(detail=True, methods=["post"], url_path="log-set")
    def log_set(self, request, pk=None):
        data = LogSetInput(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        session_obj = get_object_or_404(WorkoutSession, pk=pk)
        if request.user.role != "admin" and session_obj.user_id != request.user.id:
            raise PermissionDenied("You can only log sets on your own sessions.")
        session, row, previous = services.log_set(session_obj.user, pk, data.validated_data)
        payload = {"set": row, "session": session, "previous_best_1rm": previous}
        return Response(LogSetOutput(payload).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=WorkoutSessionSerializer)
    @action(detail=True, methods=["delete"], url_path=r"sets/(?P<set_id>[0-9a-f-]{36})")
    def remove_set(self, request, pk=None, set_id=None):
        session_obj = get_object_or_404(WorkoutSession, pk=pk)
        if request.user.role != "admin" and session_obj.user_id != request.user.id:
            raise PermissionDenied("You can only remove sets on your own sessions.")
        return self._detail(services.delete_set(session_obj.user, pk, set_id))

    @extend_schema(request=CompleteSessionInput, responses=WorkoutSessionSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        session_obj = get_object_or_404(WorkoutSession, pk=pk)
        if request.user.role != "admin" and session_obj.user_id != request.user.id:
            raise PermissionDenied("You can only complete your own sessions.")
        data = CompleteSessionInput(data=request.data)
        data.is_valid(raise_exception=True)
        return self._detail(services.complete_session(session_obj.user, pk, data.validated_data))

    @extend_schema(request=None, responses=WorkoutSessionSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        session_obj = get_object_or_404(WorkoutSession, pk=pk)
        if request.user.role != "admin" and session_obj.user_id != request.user.id:
            raise PermissionDenied("You can only cancel your own sessions.")
        return self._detail(services.cancel_session(session_obj.user, pk))


class ExerciseAnalyticsView(generics.GenericAPIView):
    permission_classes = [StaffOrMember]
    serializer_class = AnalyticsOutput

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "timeframe", str, enum=["1m", "2m", "3m", "6m", "year", "lifetime"], default="3m"
            ),
            OpenApiParameter("user_id", str, required=False),
        ],
        responses=AnalyticsOutput,
    )
    def get(self, request, exercise_id):
        query = AnalyticsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        target_user = request.user
        if request.user.role == "admin" and request.query_params.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=request.query_params["user_id"])
        result = services.exercise_analytics(
            target_user, exercise_id, query.validated_data["timeframe"]
        )
        return Response(AnalyticsOutput(result).data)


class OverallAnalyticsView(generics.GenericAPIView):
    """Aggregate progression across all workouts (Suggestion 3)."""

    permission_classes = [StaffOrMember]
    serializer_class = AnalyticsOutput

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "timeframe", str, enum=["1m", "2m", "3m", "6m", "year", "lifetime"], default="3m"
            ),
            OpenApiParameter("user_id", str, required=False),
        ],
        responses=AnalyticsOutput,
    )
    def get(self, request):
        query = AnalyticsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        target_user = request.user
        if request.user.role == "admin" and request.query_params.get("user_id"):
            from accounts.models import User

            target_user = get_object_or_404(User, pk=request.query_params["user_id"])
        result = services.overall_analytics(target_user, query.validated_data["timeframe"])
        return Response(AnalyticsOutput(result).data)
