import re
from urllib.parse import parse_qs, urlparse

import httpx
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from core.api import require_admin
from music.models import (
    ACTIVE_QUEUE_STATUSES,
    MAX_SONGS_PER_USER_DEFAULT,
    PLAYABLE_QUEUE_STATUSES,
    MusicBlockedUser,
    MusicQueueItem,
    MusicSettings,
)

YOUTUBE_ID_RE = re.compile(r"^[\w-]{11}$")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
AGE_RESTRICTED_PATTERNS = re.compile(
    r"(\b18\+\b|\bnsfw\b|\bage[\s-]*restricted\b|\badult\s+only\b|\bexplicit\s+18\+\b|\buncensored\s+18\+\b)",
    re.IGNORECASE,
)

FALLBACK_GYM_TRACKS = [
    {
        "video_id": "eVTXPUF4Oz4",
        "title": "Linkin Park - In The End (Official HD Music Video)",
        "channel_title": "Linkin Park",
        "duration_text": "3:37",
        "duration_seconds": 217,
    },
    {
        "video_id": "kXYiU_JCYtU",
        "title": "Linkin Park - Numb (Official Music Video)",
        "channel_title": "Linkin Park",
        "duration_text": "3:07",
        "duration_seconds": 187,
    },
    {
        "video_id": "btPJPFnesV4",
        "title": "Survivor - Eye of the Tiger (Official HD Video)",
        "channel_title": "SurvivorVEVO",
        "duration_text": "4:04",
        "duration_seconds": 244,
    },
    {
        "video_id": "Yhyp-_hX2s0",
        "title": "Eminem - Lose Yourself [HD]",
        "channel_title": "EminemMusic",
        "duration_text": "5:20",
        "duration_seconds": 320,
    },
    {
        "video_id": "v2AC41dglnM",
        "title": "AC/DC - Thunderstruck (Official Video)",
        "channel_title": "acdcVEVO",
        "duration_text": "4:53",
        "duration_seconds": 293,
    },
    {
        "video_id": "A_MjCqQoLLA",
        "title": "Eminem - Till I Collapse [HD]",
        "channel_title": "EminemMusic",
        "duration_text": "4:57",
        "duration_seconds": 297,
    },
    {
        "video_id": "7wtfhZwyrcc",
        "title": "Imagine Dragons - Believer (Official Music Video)",
        "channel_title": "ImagineDragonsVEVO",
        "duration_text": "3:37",
        "duration_seconds": 217,
    },
    {
        "video_id": "fJ9rUzIMcZQ",
        "title": "Queen - Bohemian Rhapsody (Official Video Remastered)",
        "channel_title": "Queen Official",
        "duration_text": "5:59",
        "duration_seconds": 359,
    },
]


def extract_youtube_video_id(value: str, *, allow_bare_id: bool = True) -> str | None:
    """Extract an 11-character YouTube video ID from a URL or raw ID string."""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None

    if allow_bare_id and YOUTUBE_ID_RE.match(raw):
        return raw

    candidate = raw
    if not candidate.startswith(("http://", "https://")) and any(
        candidate.startswith(prefix)
        for prefix in (
            "youtube.com/",
            "www.youtube.com/",
            "m.youtube.com/",
            "music.youtube.com/",
            "youtu.be/",
        )
    ):
        candidate = f"https://{candidate}"

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return None

    if host in {"youtu.be", "www.youtu.be"}:
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid if YOUTUBE_ID_RE.match(vid) else None

    if parsed.path == "/watch":
        qs = parse_qs(parsed.query)
        vid = (qs.get("v") or [""])[0]
        return vid if YOUTUBE_ID_RE.match(vid) else None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"embed", "shorts", "v", "live"}:
        vid = parts[1]
        return vid if YOUTUBE_ID_RE.match(vid) else None

    return None


def canonical_youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def default_thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def parse_duration_seconds(duration_text: str) -> int | None:
    """Convert '3:45' or '1:02:15' into total seconds."""
    if not duration_text:
        return None
    parts = duration_text.strip().split(":")
    if not (1 < len(parts) <= 3) or not all(p.isdigit() for p in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def is_age_restricted_content(title: str = "", metadata: dict | None = None) -> bool:
    if title and AGE_RESTRICTED_PATTERNS.search(title):
        return True
    if metadata:
        if metadata.get("age_restricted") or metadata.get("is_age_restricted"):
            return True
        m_title = str(metadata.get("title") or "")
        if m_title and AGE_RESTRICTED_PATTERNS.search(m_title):
            return True
    return False


def resolve_youtube_metadata(video_id: str) -> dict:
    """Fetch video title, channel name, and thumbnail via YouTube public oEmbed."""
    watch_url = canonical_youtube_url(video_id)
    fallback = {
        "video_id": video_id,
        "youtube_url": watch_url,
        "title": f"YouTube Track ({video_id})",
        "channel_title": "YouTube",
        "thumbnail_url": default_thumbnail_url(video_id),
        "duration_text": "",
        "duration_seconds": None,
        "age_restricted": False,
    }
    for preset in FALLBACK_GYM_TRACKS:
        if preset["video_id"] == video_id:
            fallback.update(preset)
            break

    try:
        resp = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": watch_url, "format": "json"},
            timeout=4.0,
        )
        if resp.status_code == 200:
            payload = resp.json()
            title = (payload.get("title") or "").strip()
            author = (payload.get("author_name") or "").strip()
            thumb = (payload.get("thumbnail_url") or "").strip()
            age_restricted = bool(
                payload.get("age_restricted") or is_age_restricted_content(title)
            )
            return {
                "video_id": video_id,
                "youtube_url": watch_url,
                "title": title or fallback["title"],
                "channel_title": author or fallback["channel_title"],
                "thumbnail_url": thumb or fallback["thumbnail_url"],
                "duration_text": fallback["duration_text"],
                "duration_seconds": fallback["duration_seconds"],
                "age_restricted": age_restricted,
            }
    except Exception:
        pass
    return fallback


def _extract_video_renderers(node, collected: list, limit: int):
    if len(collected) >= limit:
        return
    if isinstance(node, dict):
        renderer = node.get("videoRenderer")
        if isinstance(renderer, dict):
            video_id = renderer.get("videoId", "")
            if YOUTUBE_ID_RE.match(str(video_id)):
                title_runs = renderer.get("title", {}).get("runs") or []
                title = (
                    "".join(r.get("text", "") for r in title_runs)
                    or renderer.get("title", {}).get("simpleText", "")
                ).strip()
                # Skip age-restricted search results automatically
                badges = str(renderer.get("badges") or "")
                if is_age_restricted_content(title) or "age-restricted" in badges.lower():
                    return
                owner_runs = (
                    renderer.get("ownerText", {}).get("runs")
                    or renderer.get("longBylineText", {}).get("runs")
                    or []
                )
                channel_title = "".join(r.get("text", "") for r in owner_runs).strip()
                duration_text = (
                    renderer.get("lengthText", {}).get("simpleText", "")
                    or "".join(
                        r.get("text", "")
                        for r in (renderer.get("lengthText", {}).get("runs") or [])
                    )
                ).strip()
                if title and not any(x["video_id"] == video_id for x in collected):
                    collected.append(
                        {
                            "video_id": video_id,
                            "youtube_url": canonical_youtube_url(video_id),
                            "title": title[:300],
                            "channel_title": channel_title[:200],
                            "thumbnail_url": default_thumbnail_url(video_id),
                            "duration_text": duration_text[:32],
                            "duration_seconds": parse_duration_seconds(duration_text),
                        }
                    )
                    if len(collected) >= limit:
                        return
        for value in node.values():
            _extract_video_renderers(value, collected, limit)
    elif isinstance(node, list):
        for item in node:
            _extract_video_renderers(item, collected, limit)
            if len(collected) >= limit:
                return


def search_youtube(query: str, limit: int = 10) -> list[dict]:
    """Search YouTube songs by text query or direct YouTube URL."""
    cleaned = (query or "").strip()
    if not cleaned:
        return []

    results: list[dict] = []
    direct_id = extract_youtube_video_id(cleaned, allow_bare_id=False)
    if direct_id:
        meta = resolve_youtube_metadata(direct_id)
        if not is_age_restricted_content(meta.get("title", ""), meta):
            results.append(meta)
        if len(results) >= limit:
            return results[:limit]

    try:
        resp = httpx.post(
            "https://www.youtube.com/youtubei/v1/search",
            params={"prettyPrint": "false"},
            json={
                "context": {
                    "client": {
                        "clientName": "WEB",
                        "clientVersion": "2.20240726.00.00",
                        "hl": "en",
                        "gl": "US",
                    }
                },
                "query": cleaned,
            },
            timeout=5.0,
        )
        if resp.status_code == 200:
            _extract_video_renderers(resp.json(), results, limit)
    except Exception:
        pass

    if not results:
        q_lower = cleaned.lower()
        matched = [
            t
            for t in FALLBACK_GYM_TRACKS
            if q_lower in t["title"].lower() or q_lower in t["channel_title"].lower()
        ]
        source = matched if matched else FALLBACK_GYM_TRACKS
        for track in source[:limit]:
            vid = track["video_id"]
            if not any(r["video_id"] == vid for r in results):
                results.append(
                    {
                        "video_id": vid,
                        "youtube_url": canonical_youtube_url(vid),
                        "title": track["title"],
                        "channel_title": track["channel_title"],
                        "thumbnail_url": default_thumbnail_url(vid),
                        "duration_text": track["duration_text"],
                        "duration_seconds": track["duration_seconds"],
                    }
                )

    return results[:limit]


def get_settings(*, for_update: bool = False) -> MusicSettings:
    qs = MusicSettings.objects.select_for_update() if for_update else MusicSettings.objects
    obj = qs.filter(singleton_id=1).first()
    if obj is None:
        obj, _ = MusicSettings.objects.get_or_create(
            singleton_id=1,
            defaults={
                "is_enabled": True,
                "require_approval": False,
                "max_songs_per_user": MAX_SONGS_PER_USER_DEFAULT,
            },
        )
        if for_update:
            obj = MusicSettings.objects.select_for_update().get(singleton_id=1)
    return obj


def _sync_playing_track(settings_obj: MusicSettings) -> MusicQueueItem | None:
    """Ensure queue playback state matches settings_obj.is_enabled and FIFO ordering, skipping reported/pending tracks."""
    if not settings_obj.is_enabled:
        MusicQueueItem.objects.filter(status="playing").update(status="queued", started_at=None)
        return None

    # Reported tracks should not stay in 'playing'
    MusicQueueItem.objects.filter(status="playing", is_reported=True).update(
        status="queued", started_at=None
    )

    playing_items = list(
        MusicQueueItem.objects.select_for_update()
        .filter(status="playing", is_reported=False)
        .order_by("created_at", "id")
    )
    if len(playing_items) > 1:
        extra_ids = [item.id for item in playing_items[1:]]
        MusicQueueItem.objects.filter(id__in=extra_ids).update(status="queued", started_at=None)
        return playing_items[0]
    if len(playing_items) == 1:
        return playing_items[0]

    next_item = (
        MusicQueueItem.objects.select_for_update()
        .filter(status="queued", is_reported=False)
        .order_by("created_at", "id")
        .first()
    )
    if next_item:
        next_item.status = "playing"
        next_item.started_at = timezone.now()
        next_item.save(update_fields=["status", "started_at", "updated_at"])
        return next_item
    return None


def _requester_display(user) -> tuple[str, str]:
    name = (user.full_name or "").strip() or "Gym Member"
    if user.role == "admin":
        staff_profile = getattr(user, "staff_profile", None)
        short_id = getattr(staff_profile, "short_id", "") or "STAFF"
        return (user.full_name or "Gym Staff").strip(), short_id
    member_profile = getattr(user, "member_profile", None)
    member_id = getattr(member_profile, "member_id", "") or ""
    return name, member_id


def serialize_queue_item(
    item: MusicQueueItem, current_user=None, position: int | None = None
) -> dict:
    requester_name, requester_code = _requester_display(item.user)
    is_owner = bool(
        current_user and current_user.is_authenticated and item.user_id == current_user.id
    )
    is_admin = bool(current_user and current_user.is_authenticated and current_user.role == "admin")
    can_remove = item.status in ACTIVE_QUEUE_STATUSES and (is_admin or is_owner)
    can_report = (
        item.status in PLAYABLE_QUEUE_STATUSES
        and not item.is_reported
        and not is_owner
    )
    return {
        "id": item.id,
        "video_id": item.video_id,
        "youtube_url": item.youtube_url,
        "title": item.title,
        "channel_title": item.channel_title,
        "thumbnail_url": item.thumbnail_url or default_thumbnail_url(item.video_id),
        "duration_seconds": item.duration_seconds,
        "duration_text": item.duration_text,
        "status": item.status,
        "is_reported": item.is_reported,
        "report_reason": item.report_reason,
        "position": position,
        "requested_by_id": item.user_id,
        "requested_by_name": requester_name,
        "requested_by_code": requester_code,
        "is_own_song": is_owner,
        "can_remove": can_remove,
        "can_report": can_report,
        "created_at": item.created_at,
        "started_at": item.started_at,
        "ended_at": item.ended_at,
    }


@transaction.atomic
def get_queue_state(user) -> dict:
    settings_obj = get_settings(for_update=True)
    _sync_playing_track(settings_obj)

    is_admin = bool(user and user.is_authenticated and user.role == "admin")
    is_user_blocked = bool(
        user
        and user.is_authenticated
        and MusicBlockedUser.objects.filter(user=user).exists()
    )

    # Playable queue excludes reported items and pending_approval items
    playable_items = list(
        MusicQueueItem.objects.filter(status__in=PLAYABLE_QUEUE_STATUSES, is_reported=False)
        .select_related("user", "user__member_profile", "user__staff_profile")
        .order_by("created_at", "id")
    )
    playing_list = [i for i in playable_items if i.status == "playing"]
    queued_list = [i for i in playable_items if i.status == "queued"]
    ordered_active = playing_list + queued_list

    serialized_queue = [
        serialize_queue_item(item, current_user=user, position=idx + 1)
        for idx, item in enumerate(ordered_active)
    ]
    now_playing = serialized_queue[0] if playing_list else None

    # Pending approval items (admins see all; members see their own pending items)
    pending_qs = (
        MusicQueueItem.objects.filter(status="pending_approval", is_reported=False)
        .select_related("user", "user__member_profile", "user__staff_profile")
        .order_by("created_at", "id")
    )
    if not is_admin and user and user.is_authenticated:
        pending_qs = pending_qs.filter(user=user)
    serialized_pending = [
        serialize_queue_item(item, current_user=user, position=None) for item in pending_qs
    ]

    # Reported items (hidden from members, visible to admin for review)
    serialized_reported = []
    serialized_blocked = []
    if is_admin:
        reported_qs = (
            MusicQueueItem.objects.filter(status__in=ACTIVE_QUEUE_STATUSES, is_reported=True)
            .select_related("user", "user__member_profile", "user__staff_profile")
            .order_by("-reported_at", "created_at")
        )
        serialized_reported = [
            serialize_queue_item(item, current_user=user, position=None) for item in reported_qs
        ]
        blocks_qs = MusicBlockedUser.objects.select_related(
            "user", "user__member_profile", "user__staff_profile"
        ).all()
        for b in blocks_qs:
            b_name, b_code = _requester_display(b.user)
            serialized_blocked.append(
                {
                    "user_id": b.user_id,
                    "full_name": b_name,
                    "member_code": b_code,
                    "reason": b.reason,
                    "blocked_at": b.created_at,
                }
            )

    recent_history = list(
        MusicQueueItem.objects.filter(status__in=("played", "skipped"))
        .select_related("user", "user__member_profile", "user__staff_profile")
        .order_by("-ended_at", "-created_at")[:10]
    )
    serialized_history = [
        serialize_queue_item(item, current_user=user, position=None) for item in recent_history
    ]

    user_active_count = (
        MusicQueueItem.objects.filter(user=user, status__in=ACTIVE_QUEUE_STATUSES).count()
        if user and user.is_authenticated
        else 0
    )
    max_per_user = settings_obj.max_songs_per_user
    return {
        "is_enabled": settings_obj.is_enabled,
        "require_approval": settings_obj.require_approval,
        "max_songs_per_user": max_per_user,
        "user_active_count": user_active_count,
        "remaining_slots": max(0, max_per_user - user_active_count),
        "is_user_blocked": is_user_blocked,
        "now_playing": now_playing,
        "queue": serialized_queue,
        "pending_approval": serialized_pending,
        "reported_items": serialized_reported,
        "blocked_users": serialized_blocked,
        "history": serialized_history,
    }


@transaction.atomic
def add_song_to_queue(user, data: dict) -> dict:
    settings_obj = get_settings(for_update=True)
    if not settings_obj.is_enabled:
        raise ValidationError({"detail": "The gym music queue is currently turned off by staff."})

    if MusicBlockedUser.objects.filter(user=user).exists():
        raise PermissionDenied("You have been blocked by an admin from adding songs to the gym music queue.")

    raw_source = (data.get("youtube_url") or data.get("video_id") or "").strip()
    video_id = extract_youtube_video_id(raw_source, allow_bare_id=True)
    if not video_id:
        raise ValidationError(
            {"youtube_url": "Enter a valid YouTube song link or 11-character video ID."}
        )

    # Lock active queue items to prevent race conditions on the per-user limit
    user_active_items = list(
        MusicQueueItem.objects.select_for_update().filter(
            user=user, status__in=ACTIVE_QUEUE_STATUSES
        )
    )
    max_songs = settings_obj.max_songs_per_user
    if len(user_active_items) >= max_songs:
        raise ValidationError(
            {
                "detail": (
                    f"You already have {max_songs} songs in the queue (maximum {max_songs} allowed). "
                    "Wait for a song to finish or remove one before adding another."
                )
            }
        )

    provided_title = (data.get("title") or "").strip()
    provided_channel = (data.get("channel_title") or "").strip()
    provided_thumb = (data.get("thumbnail_url") or "").strip()
    provided_duration_text = (data.get("duration_text") or "").strip()
    provided_duration_seconds = data.get("duration_seconds")

    meta = None
    if not provided_title:
        meta = resolve_youtube_metadata(video_id)
        title = meta["title"]
        channel_title = provided_channel or meta["channel_title"]
        thumbnail_url = provided_thumb or meta["thumbnail_url"]
        duration_text = provided_duration_text or meta.get("duration_text", "")
        duration_seconds = (
            provided_duration_seconds
            if provided_duration_seconds is not None
            else meta.get("duration_seconds")
        )
    else:
        title = provided_title[:300]
        channel_title = provided_channel[:200]
        thumbnail_url = provided_thumb or default_thumbnail_url(video_id)
        duration_text = provided_duration_text[:32]
        duration_seconds = (
            provided_duration_seconds
            if provided_duration_seconds is not None
            else parse_duration_seconds(duration_text)
        )

    if is_age_restricted_content(title, meta):
        raise ValidationError(
            {"youtube_url": "Age-restricted videos are blocked and cannot be added to the gym queue."}
        )

    initial_status = (
        "pending_approval"
        if (settings_obj.require_approval and user.role != "admin")
        else "queued"
    )

    item = MusicQueueItem.objects.create(
        user=user,
        video_id=video_id,
        youtube_url=canonical_youtube_url(video_id),
        title=title,
        channel_title=channel_title,
        thumbnail_url=thumbnail_url,
        duration_seconds=duration_seconds,
        duration_text=duration_text,
        status=initial_status,
    )

    _sync_playing_track(settings_obj)
    item.refresh_from_db()

    state = get_queue_state(user)
    position = next(
        (entry["position"] for entry in state["queue"] if str(entry["id"]) == str(item.id)),
        None if item.status == "pending_approval" else len(state["queue"]),
    )
    return {
        "item": serialize_queue_item(item, current_user=user, position=position),
        "queue_state": state,
    }


@transaction.atomic
def remove_song_from_queue(actor, item_id) -> dict:
    settings_obj = get_settings(for_update=True)
    item = get_object_or_404(MusicQueueItem.objects.select_for_update(), pk=item_id)

    if item.status not in ACTIVE_QUEUE_STATUSES:
        raise ValidationError({"detail": "This song is no longer in the active queue."})

    if actor.role != "admin" and item.user_id != actor.id:
        raise PermissionDenied("Only staff or the member who added this song can remove it.")

    item.status = "removed"
    item.ended_at = timezone.now()
    item.removed_by = actor
    item.save(update_fields=["status", "ended_at", "removed_by", "updated_at"])

    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def approve_song_in_queue(actor, item_id) -> dict:
    """Admin approves a member song that was waiting for approval (Suggestion 11)."""
    require_admin(actor)
    settings_obj = get_settings(for_update=True)
    item = get_object_or_404(MusicQueueItem.objects.select_for_update(), pk=item_id)
    if item.status != "pending_approval":
        raise ValidationError({"detail": "This song is not waiting for approval."})
    item.status = "queued"
    item.is_reported = False
    item.approved_by = actor
    item.save(update_fields=["status", "is_reported", "approved_by", "updated_at"])
    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def report_song_in_queue(actor, item_id, reason: str = "") -> dict:
    """Member or staff flags a bad song, hiding it from the queue until admin checks it (Suggestion 11)."""
    settings_obj = get_settings(for_update=True)
    item = get_object_or_404(MusicQueueItem.objects.select_for_update(), pk=item_id)
    if item.status not in ACTIVE_QUEUE_STATUSES:
        raise ValidationError({"detail": "This song is no longer in the active queue."})

    item.is_reported = True
    item.reported_by = actor
    item.report_reason = (reason or "Reported by member").strip()[:200]
    item.reported_at = timezone.now()
    if item.status == "playing":
        item.status = "queued"
        item.started_at = None
    item.save(
        update_fields=[
            "status",
            "started_at",
            "is_reported",
            "reported_by",
            "report_reason",
            "reported_at",
            "updated_at",
        ]
    )
    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def restore_reported_song(actor, item_id) -> dict:
    """Admin dismisses a flag/report on a song and restores it to the active queue (Suggestion 11)."""
    require_admin(actor)
    settings_obj = get_settings(for_update=True)
    item = get_object_or_404(MusicQueueItem.objects.select_for_update(), pk=item_id)
    item.is_reported = False
    item.report_reason = ""
    if item.status == "pending_approval":
        item.status = "queued"
    item.save(update_fields=["is_reported", "report_reason", "status", "updated_at"])
    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def block_music_user(actor, target_user_id, reason: str = "") -> dict:
    """Admin blocks a user who keeps adding bad songs and removes their active songs (Suggestion 11)."""
    require_admin(actor)
    settings_obj = get_settings(for_update=True)
    target_user = get_object_or_404(User, pk=target_user_id)
    if target_user.role == "admin":
        raise ValidationError({"user_id": "Staff accounts cannot be blocked from the music queue."})
    MusicBlockedUser.objects.update_or_create(
        user=target_user,
        defaults={
            "blocked_by": actor,
            "reason": (reason or "Repeated inappropriate song submissions").strip()[:240],
        },
    )
    now = timezone.now()
    MusicQueueItem.objects.filter(
        user=target_user, status__in=ACTIVE_QUEUE_STATUSES
    ).update(status="removed", ended_at=now, removed_by=actor, updated_at=now)
    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def unblock_music_user(actor, target_user_id) -> dict:
    """Admin unblocks a previously blocked user (Suggestion 11)."""
    require_admin(actor)
    MusicBlockedUser.objects.filter(user_id=target_user_id).delete()
    return get_queue_state(actor)


@transaction.atomic
def skip_current_song(actor) -> dict:
    require_admin(actor)
    settings_obj = get_settings(for_update=True)
    current = (
        MusicQueueItem.objects.select_for_update()
        .filter(status__in=PLAYABLE_QUEUE_STATUSES, is_reported=False)
        .order_by("-status", "created_at", "id")
        .first()
    )
    playing = (
        MusicQueueItem.objects.select_for_update()
        .filter(status="playing", is_reported=False)
        .order_by("created_at", "id")
        .first()
    )
    target = playing or current
    if target:
        target.status = "skipped"
        target.ended_at = timezone.now()
        target.removed_by = actor
        target.save(update_fields=["status", "ended_at", "removed_by", "updated_at"])

    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def complete_current_song(actor, item_id=None) -> dict:
    require_admin(actor)
    settings_obj = get_settings(for_update=True)
    qs = MusicQueueItem.objects.select_for_update().filter(status="playing")
    if item_id:
        qs = qs.filter(pk=item_id)
    playing = qs.order_by("created_at", "id").first()

    if playing:
        playing.status = "played"
        playing.ended_at = timezone.now()
        playing.save(update_fields=["status", "ended_at", "updated_at"])

    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def update_music_settings(actor, data: dict) -> dict:
    require_admin(actor)
    settings_obj = get_settings(for_update=True)
    updated_fields = ["updated_by", "updated_at"]
    if "is_enabled" in data:
        settings_obj.is_enabled = bool(data["is_enabled"])
        updated_fields.append("is_enabled")
    if "require_approval" in data:
        settings_obj.require_approval = bool(data["require_approval"])
        updated_fields.append("require_approval")
    if "max_songs_per_user" in data and data["max_songs_per_user"] is not None:
        settings_obj.max_songs_per_user = int(data["max_songs_per_user"])
        updated_fields.append("max_songs_per_user")
    settings_obj.updated_by = actor
    settings_obj.save(update_fields=updated_fields)

    _sync_playing_track(settings_obj)
    return get_queue_state(actor)


@transaction.atomic
def set_queue_enabled(actor, is_enabled: bool) -> dict:
    return update_music_settings(actor, {"is_enabled": is_enabled})
