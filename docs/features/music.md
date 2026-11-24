# Music (FloorCue)

Gym floor YouTube request queue. Members request tracks; staff approve (inbox-first by
default), then play from the admin app.

- **OpenAPI:** `/openapi/v1/music.yaml`
- **Base path:** `/api/v1/music/`
- **Auth:** Bearer member or staff (staff mutations need `music.update`)

## Flow

1. Member searches (`GET /search/?q=`) or pastes a YouTube URL and `POST /queue/`.
2. With `require_approval=true` (default), the item is `pending_approval` (inbox).
3. Staff `POST /queue/{id}/approve/` → `queued`. Reject = `DELETE /queue/{id}/`.
4. Staff `POST /queue/play/` starts the head of the playable queue (`playing`).
5. On song end: `POST /queue/complete/`; skip: `POST /queue/skip/`.
6. Staff may `POST /blocks/` / `DELETE /blocks/{user_id}/` to block members from FloorCue.
7. Recently played: `DELETE /queue/history/{id}/`, `DELETE /queue/history/` (clear all),
   or `POST /queue/history/{id}/play/` to replay immediately.
8. Curated mix: `GET /playlists/gym/` then `POST /playlists/gym/enqueue/` (optional `video_ids`).

Playback does **not** auto-start on `GET` or add — only staff play / skip / complete /
remove-of-playing advance the player. Gym playlist enqueue also does not auto-play.

## Settings

`POST|PATCH /settings/` — `is_enabled`, `require_approval` (default **true**),
`max_songs_per_user` (1–10). Staff adds always skip the inbox.

## 18+ filter

Always on for search, add, and approve (title/channel heuristics + YouTube age badges).
Not perfect without YouTube Data API; inbox-first is the human backstop.

## Permissions

| Code | Use |
|---|---|
| `music.view` | Open FloorCue / read queue (client gate) |
| `music.update` | Play, skip, complete, approve, settings, block/unblock |

## Honest limits

Keyword + badge filtering catches many age-gated videos, not all. Official YouTube Music /
Spotify remote control is out of scope.
