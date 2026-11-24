from rest_framework import serializers

from music.models import QUEUE_STATUS_CHOICES


class YouTubeSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, default="", max_length=300)


class YouTubeSearchResultSerializer(serializers.Serializer):
    video_id = serializers.CharField()
    youtube_url = serializers.URLField()
    title = serializers.CharField()
    channel_title = serializers.CharField(allow_blank=True)
    thumbnail_url = serializers.URLField(allow_blank=True)
    duration_text = serializers.CharField(allow_blank=True)
    duration_seconds = serializers.IntegerField(allow_null=True)


class YouTubeSearchOutputSerializer(serializers.Serializer):
    results = YouTubeSearchResultSerializer(many=True)


class MusicQueueItemOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    video_id = serializers.CharField()
    youtube_url = serializers.URLField()
    title = serializers.CharField()
    channel_title = serializers.CharField(allow_blank=True)
    thumbnail_url = serializers.URLField(allow_blank=True)
    duration_seconds = serializers.IntegerField(allow_null=True)
    duration_text = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=QUEUE_STATUS_CHOICES)
    is_reported = serializers.BooleanField(required=False)
    report_reason = serializers.CharField(allow_blank=True, required=False)
    position = serializers.IntegerField(allow_null=True)
    requested_by_id = serializers.UUIDField()
    requested_by_name = serializers.CharField()
    requested_by_code = serializers.CharField(allow_blank=True)
    is_own_song = serializers.BooleanField()
    can_remove = serializers.BooleanField()
    can_report = serializers.BooleanField(required=False)
    created_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    ended_at = serializers.DateTimeField(allow_null=True)


class MusicBlockedUserOutputSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    full_name = serializers.CharField()
    member_code = serializers.CharField(allow_blank=True)
    reason = serializers.CharField(allow_blank=True)
    blocked_at = serializers.DateTimeField()


class MusicQueueStateOutputSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField()
    require_approval = serializers.BooleanField(required=False)
    is_playback_active = serializers.BooleanField(required=False)
    max_songs_per_user = serializers.IntegerField()
    user_active_count = serializers.IntegerField()
    remaining_slots = serializers.IntegerField()
    is_user_blocked = serializers.BooleanField(required=False)
    now_playing = MusicQueueItemOutputSerializer(allow_null=True)
    queue = MusicQueueItemOutputSerializer(many=True)
    pending_approval = MusicQueueItemOutputSerializer(many=True, required=False)
    reported_items = MusicQueueItemOutputSerializer(many=True, required=False)
    blocked_users = MusicBlockedUserOutputSerializer(many=True, required=False)
    history = MusicQueueItemOutputSerializer(many=True)


class MusicPlaybackInputSerializer(serializers.Serializer):
    is_playback_active = serializers.BooleanField()


class MusicQueueAddInputSerializer(serializers.Serializer):
    youtube_url = serializers.CharField(required=False, allow_blank=True, max_length=500)
    video_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    title = serializers.CharField(required=False, allow_blank=True, max_length=300)
    channel_title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    thumbnail_url = serializers.URLField(required=False, allow_blank=True, max_length=1000)
    duration_text = serializers.CharField(required=False, allow_blank=True, max_length=32)
    duration_seconds = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=86400
    )


class MusicQueueAddOutputSerializer(serializers.Serializer):
    item = MusicQueueItemOutputSerializer()
    queue_state = MusicQueueStateOutputSerializer()


class MusicQueueCompleteInputSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(required=False, allow_null=True)


class MusicQueueReorderInputSerializer(serializers.Serializer):
    item_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
        help_text="Queued item IDs in the desired play order.",
    )


class MusicSettingsInputSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=False)
    require_approval = serializers.BooleanField(required=False)
    max_songs_per_user = serializers.IntegerField(min_value=1, max_value=10, required=False)


class MusicReportInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class MusicBlockUserInputSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")


class MusicPlaylistTrackSerializer(serializers.Serializer):
    video_id = serializers.CharField()
    youtube_url = serializers.URLField()
    title = serializers.CharField()
    channel_title = serializers.CharField(allow_blank=True)
    thumbnail_url = serializers.URLField(allow_blank=True)
    duration_text = serializers.CharField(allow_blank=True)
    duration_seconds = serializers.IntegerField(allow_null=True)


class MusicPlaylistOutputSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    tracks = MusicPlaylistTrackSerializer(many=True)


class MusicPlaylistEnqueueInputSerializer(serializers.Serializer):
    video_ids = serializers.ListField(
        child=serializers.CharField(max_length=16),
        required=False,
        allow_empty=False,
        max_length=40,
    )


class MusicPlaylistEnqueueOutputSerializer(serializers.Serializer):
    added = serializers.IntegerField()
    skipped_existing = serializers.IntegerField()
    skipped_filtered = serializers.IntegerField()
    queue_state = MusicQueueStateOutputSerializer()
