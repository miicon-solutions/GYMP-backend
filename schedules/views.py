from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from schedules import services
from schedules.serializers import (
    AutoPopulateInput,
    CreateCycleInput,
    ScheduledDayUpdateSerializer,
    SplitPlannerCycleSerializer,
)


class ActiveCycleView(generics.GenericAPIView):
    """Retrieve or configure the user's active periodization / split planner cycle."""

    permission_classes = [IsAuthenticated]
    serializer_class = SplitPlannerCycleSerializer

    @extend_schema(responses=SplitPlannerCycleSerializer)
    def get(self, request):
        cycle = services.active_cycle(request.user)
        return Response(SplitPlannerCycleSerializer(cycle).data)

    @extend_schema(request=CreateCycleInput, responses={201: SplitPlannerCycleSerializer})
    def post(self, request):
        serializer = CreateCycleInput(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        cycle = services.create_cycle(request.user, serializer.validated_data)
        return Response(SplitPlannerCycleSerializer(cycle).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CreateCycleInput, responses=SplitPlannerCycleSerializer)
    def patch(self, request):
        serializer = CreateCycleInput(data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        cycle = services.update_cycle(request.user, serializer.validated_data)
        return Response(SplitPlannerCycleSerializer(cycle).data)


class ActiveCycleDayView(generics.GenericAPIView):
    """Assign or swap a routine on a specific day of the active microcycle."""

    permission_classes = [IsAuthenticated]
    serializer_class = ScheduledDayUpdateSerializer

    @extend_schema(request=ScheduledDayUpdateSerializer, responses=SplitPlannerCycleSerializer)
    def put(self, request, day_index):
        serializer = ScheduledDayUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        cycle = services.update_day(request.user, day_index, serializer.validated_data)
        return Response(SplitPlannerCycleSerializer(cycle).data)


class AutoPopulateCycleView(generics.GenericAPIView):
    """Auto-fill active cycle days with matching routines based on split templates (PPL, Upper/Lower, Full Body)."""

    permission_classes = [IsAuthenticated]
    serializer_class = AutoPopulateInput

    @extend_schema(request=AutoPopulateInput, responses=SplitPlannerCycleSerializer)
    def post(self, request):
        serializer = AutoPopulateInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        cycle = services.auto_populate(
            request.user,
            template=serializer.validated_data["template"],
            prefer_custom=serializer.validated_data.get("prefer_custom", True),
        )
        return Response(SplitPlannerCycleSerializer(cycle).data)
