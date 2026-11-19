from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import Entity

QUEUE_STATUS_CHOICES = [
    ("pending_approval", "Pending Approval"),
    ("queued", "Queued"),
    ("playing", "Playing"),
    ("played", "Played"),
    ("skipped", "Skipped"),
    ("removed", "Removed"),
]

ACTIVE_QUEUE_STATUSES = ("queued", "playing", "pending_approval")
PLAYABLE_QUEUE_STATUSES = ("queued", "playing")
MAX_SONGS_PER_USER_DEFAULT = 3


class MusicSettings(models.Model):
    """Singleton configuration for the gym music player and member song queue."""

    singleton_id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    is_enabled = models.BooleanField(default=True)
    require_approval = models.BooleanField(default=False)
    max_songs_per_user = models.PositiveSmallIntegerField(
        default=MAX_SONGS_PER_USER_DEFAULT,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="music_settings_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton_id=1),
                name="music_settings_singleton",
            ),
        ]

    def __str__(self):
        state = "enabled" if self.is_enabled else "disabled"
        return f"Gym Music Queue ({state}, max {self.max_songs_per_user}/user)"


class MusicBlockedUser(Entity):
    """A member blocked by staff/admin from adding songs to the gym music queue (Suggestion 11)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="music_block",
    )
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_music_blocks",
    )
    reason = models.CharField(max_length=240, blank=True, default="")

    class Meta(Entity.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"Blocked music user {self.user_id}"


class MusicQueueItem(Entity):
    """A YouTube song queued by a gym member or staff to play in FIFO order."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="music_queue_items",
    )
    video_id = models.CharField(max_length=16, db_index=True)
    youtube_url = models.URLField(max_length=500)
    title = models.CharField(max_length=300)
    channel_title = models.CharField(max_length=200, blank=True, default="")
    thumbnail_url = models.URLField(max_length=1000, blank=True, default="")
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    duration_text = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=QUEUE_STATUS_CHOICES,
        default="queued",
        db_index=True,
    )
    is_reported = models.BooleanField(default=False, db_index=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_music_queue_items",
    )
    report_reason = models.CharField(max_length=200, blank=True, default="")
    reported_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_music_queue_items",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="removed_music_queue_items",
    )

    class Meta(Entity.Meta):
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="music_queue_status_idx"),
            models.Index(fields=["user", "status"], name="music_queue_user_status_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.video_id}) [{self.status}]"
