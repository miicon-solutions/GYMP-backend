from django.urls import path
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api import AdminOnly, StaffOrMember
from music import services
from music.serializers import (
    MusicBlockUserInputSerializer,
    MusicQueueAddInputSerializer,
    MusicQueueAddOutputSerializer,
    MusicQueueCompleteInputSerializer,
    MusicQueueStateOutputSerializer,
    MusicReportInputSerializer,
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


class MusicQueueApproveView(APIView):
    """Staff action to approve a pending member song so it enters the playback queue."""

    permission_classes = [AdminOnly]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        request=None,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def post(self, request, pk):
        return Response(services.approve_song_in_queue(request.user, pk))


class MusicQueueReportView(APIView):
    """Member or staff action to flag a bad song, hiding it until admin reviews it."""

    permission_classes = [StaffOrMember]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        request=MusicReportInputSerializer,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def post(self, request, pk):
        serializer = MusicReportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            services.report_song_in_queue(
                request.user, pk, serializer.validated_data.get("reason", "")
            )
        )


class MusicQueueRestoreView(APIView):
    """Staff action to dismiss a report on a song and restore it to the active queue."""

    permission_classes = [AdminOnly]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        request=None,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def post(self, request, pk):
        return Response(services.restore_reported_song(request.user, pk))


class MusicBlockUserListView(APIView):
    """Staff action to block a member from adding songs to the gym music queue."""

    permission_classes = [AdminOnly]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        request=MusicBlockUserInputSerializer,
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def post(self, request):
        serializer = MusicBlockUserInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            services.block_music_user(
                request.user,
                serializer.validated_data["user_id"],
                serializer.validated_data.get("reason", ""),
            )
        )


class MusicBlockUserDetailView(APIView):
    """Staff action to unblock a member so they can add songs again."""

    permission_classes = [AdminOnly]
    serializer_class = MusicQueueStateOutputSerializer

    @extend_schema(
        responses={200: MusicQueueStateOutputSerializer},
        tags=["music"],
    )
    def delete(self, request, user_id):
        return Response(services.unblock_music_user(request.user, user_id))


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
    """Staff action to configure the gym music queue (enable/disable, require approval, max songs per user)."""

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
        return Response(services.update_music_settings(request.user, serializer.validated_data))

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
    path("queue/<uuid:pk>/approve/", MusicQueueApproveView.as_view(), name="music-queue-approve"),
    path("queue/<uuid:pk>/report/", MusicQueueReportView.as_view(), name="music-queue-report"),
    path("queue/<uuid:pk>/restore/", MusicQueueRestoreView.as_view(), name="music-queue-restore"),
    path("blocks/", MusicBlockUserListView.as_view(), name="music-blocks"),
    path("blocks/<uuid:user_id>/", MusicBlockUserDetailView.as_view(), name="music-block-detail"),
    path("settings/", MusicSettingsView.as_view(), name="music-settings"),
    path("search/", MusicYouTubeSearchView.as_view(), name="music-search"),
]
