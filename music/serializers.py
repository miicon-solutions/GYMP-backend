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
    position = serializers.IntegerField(allow_null=True)
    requested_by_id = serializers.UUIDField()
    requested_by_name = serializers.CharField()
    requested_by_code = serializers.CharField(allow_blank=True)
    is_own_song = serializers.BooleanField()
    can_remove = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    ended_at = serializers.DateTimeField(allow_null=True)


class MusicQueueStateOutputSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField()
    max_songs_per_user = serializers.IntegerField()
    user_active_count = serializers.IntegerField()
    remaining_slots = serializers.IntegerField()
    now_playing = MusicQueueItemOutputSerializer(allow_null=True)
    queue = MusicQueueItemOutputSerializer(many=True)
    history = MusicQueueItemOutputSerializer(many=True)


class MusicQueueAddInputSerializer(serializers.Serializer):
    youtube_url = serializers.CharField(required=False, allow_blank=True, max_length=500)
    video_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    title = serializers.CharField(required=False, allow_blank=True, max_length=300)
    channel_title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    thumbnail_url = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    duration_text = serializers.CharField(required=False, allow_blank=True, max_length=32)
    duration_seconds = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=86400
    )


class MusicQueueAddOutputSerializer(serializers.Serializer):
    item = MusicQueueItemOutputSerializer()
    queue_state = MusicQueueStateOutputSerializer()


class MusicQueueCompleteInputSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(required=False, allow_null=True)


class MusicSettingsInputSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField()
