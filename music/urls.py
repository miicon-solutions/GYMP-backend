from django.urls import path
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import AdminOnly, StaffOrMember
from music import services
from music.serializers import (
    MusicQueueAddInputSerializer,
    MusicQueueAddOutputSerializer,
    MusicQueueCompleteInputSerializer,
    MusicQueueStateOutputSerializer,
    MusicSettingsInputSerializer,
    YouTubeSearchOutputSerializer,
    YouTubeSearchQuerySerializer,
)


class MusicQueueView(APIView):
    """Retrieve the gym music queue state or add a YouTube song to the queue."""

    permission_classes = [StaffOrMember]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def get(self, request):
        return Response(services.get_queue_state(request.user))

    @extend_schema(
        request=MusicQueueAddInputSerializer,
        responses={201: MusicQueueAddOutputSerializer},
        tags=["music"],
    )
    def post(self, request):
        serializer = MusicQueueAddInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.add_song_to_queue(request.user, serializer.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)


class MusicQueueItemView(APIView):
    """Remove a song from the gym music queue (staff can remove any song; members can remove their own)."""

    permission_classes = [StaffOrMember]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def delete(self, request, pk):
        return Response(services.remove_song_from_queue(request.user, pk))


class MusicQueueSkipView(APIView):
    """Staff action to skip the currently playing song and advance to the next song in queue."""

    permission_classes = [AdminOnly]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        request=None,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def post(self, request):
        return Response(services.skip_current_song(request.user))


class MusicQueueCompleteView(APIView):
    """Advance the gym player on /admin/music to the next song in queue when the current song finishes playing."""

    permission_classes = [AdminOnly]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        request=MusicQueueCompleteInputSerializer,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def post(self, request):
        serializer = MusicQueueCompleteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            services.complete_current_song(request.user, serializer.validated_data.get("item_id"))
        )


class MusicSettingsView(APIView):
    """Staff action to enable or turn off the gym music queue system."""

    permission_classes = [AdminOnly]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        request=MusicSettingsInputSerializer,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def post(self, request):
        serializer = MusicSettingsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            services.set_queue_enabled(request.user, serializer.validated_data["is_enabled"])
        )

    @extend_schema(
        request=MusicSettingsInputSerializer,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def patch(self, request):
        return self.post(request)


class MusicYouTubeSearchView(APIView):
    """Search YouTube for songs or resolve a pasted YouTube link."""

    permission_classes = [StaffOrMember]
    serializer_class = YouTubeSearchOutputSerializer

    @extend_schema(
        parameters=[OpenApiParameter("q", str, OpenApiParameter.QUERY)],
        responses={200: YouTubeSearchOutputSerializer},
        tags=["music"],
    )
    def get(self, request):
        serializer = YouTubeSearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        results = services.search_youtube(serializer.validated_data.get("q", ""))
        return Response({"results": results})


urlpatterns = [
    path("queue/", MusicQueueView.as_view(), name="music-queue"),
    path("queue/skip/", MusicQueueSkipView.as_view(), name="music-queue-skip"),
    path("queue/complete/", MusicQueueCompleteView.as_view(), name="music-queue-complete"),
    path("queue/<uuid:pk>/", MusicQueueItemView.as_view(), name="music-queue-item"),
    path("settings/", MusicSettingsView.as_view(), name="music-settings"),
    path("search/", MusicYouTubeSearchView.as_view(), name="music-search"),
]
