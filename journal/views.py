from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.api import ordered_pagination
from journal import services
from journal.filters import JournalFilter
from journal.models import GymJournalEntry
from journal.serializers import (
    GymJournalEntryInputSerializer,
    GymJournalEntrySerializer,
)


class JournalEntryListView(generics.ListCreateAPIView):
    """List paginated gym journal entries with subjective ratings and tags, or log a new reflection."""

    permission_classes = [IsAuthenticated]
    pagination_class = ordered_pagination("-date", "-created_at", "-id")
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = JournalFilter
    search_fields = ["subjective_notes", "protocol_adjustments"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return GymJournalEntryInputSerializer
        return GymJournalEntrySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GymJournalEntry.objects.none()
        return services.list_entries(self.request.user)

    @extend_schema(responses=GymJournalEntrySerializer(many=True))
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=GymJournalEntryInputSerializer, responses={201: GymJournalEntrySerializer}
    )
    def post(self, request, *args, **kwargs):
        serializer = GymJournalEntryInputSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        entry = services.save_entry(request.user, serializer.validated_data)
        return Response(GymJournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class JournalEntryTodayView(generics.GenericAPIView):
    """Retrieve or initialize today's readiness score and reflection entry."""

    permission_classes = [IsAuthenticated]
    serializer_class = GymJournalEntrySerializer

    @extend_schema(responses=GymJournalEntrySerializer)
    def get(self, request):
        entry = services.get_or_create_today(request.user)
        return Response(GymJournalEntrySerializer(entry).data)

    @extend_schema(
        request=GymJournalEntryInputSerializer, responses={200: GymJournalEntrySerializer}
    )
    def post(self, request):
        entry = services.get_or_create_today(request.user)
        serializer = GymJournalEntryInputSerializer(
            data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        entry = services.save_entry(request.user, serializer.validated_data, instance=entry)
        return Response(GymJournalEntrySerializer(entry).data)


class JournalEntryDetailView(generics.RetrieveUpdateAPIView):
    """Retrieve or update a specific gym journal entry."""

    permission_classes = [IsAuthenticated]
    lookup_field = "pk"

    def get_serializer_class(self):
        if self.request.method in ["PUT", "PATCH"]:
            return GymJournalEntryInputSerializer
        return GymJournalEntrySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GymJournalEntry.objects.none()
        return services.list_entries(self.request.user)

    @extend_schema(responses=GymJournalEntrySerializer)
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=GymJournalEntryInputSerializer, responses=GymJournalEntrySerializer)
    def patch(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = GymJournalEntryInputSerializer(
            data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        entry = services.save_entry(request.user, serializer.validated_data, instance=instance)
        return Response(GymJournalEntrySerializer(entry).data)

    @extend_schema(request=GymJournalEntryInputSerializer, responses=GymJournalEntrySerializer)
    def put(self, request, *args, **kwargs):
        return self.patch(request, *args, **kwargs)
