# Music (FloorCue)

Gym floor YouTube request queue. Members request tracks; staff approve (inbox-first by
default), then play from the admin app.

- **OpenAPI:** `/openapi/v1/music.yaml`
- **Base path:** `/api/v1/music/`
- **Auth:** Bearer member or staff (staff mutations need `music.update`)

## Flow

1. Member searches (`GET /search/?q=`) or pastes a YouTube URL and `POST /queue/`.
2. With `require_approval=true` (default), the item is `pending_approval` (inbox).
   Staff with `music.view` get inbox + FCM (`code=music_request`); tap → admin FloorCue.
3. Staff `POST /queue/{id}/approve/` → `queued` (member gets `music_request_approved` push).
   Reject = `DELETE /queue/{id}/` while pending (member gets `music_request_rejected`).
   Both mark staff `music_request` inbox rows read. Member self-withdraw marks read only.
4. Staff `POST /queue/play/` starts the head of the playable queue (`playing`) and
   sets `is_playback_active=true`.
5. Staff pause/resume on the gym speaker: `POST /queue/playback/` with
   `{ "is_playback_active": false|true }` (keeps `now_playing`; members poll this for
   Lottie vs pause UI).
6. On song end: `POST /queue/complete/`; skip: `POST /queue/skip/`.
7. Staff may `POST /blocks/` / `DELETE /blocks/{user_id}/` to block members from FloorCue.
8. Recently played: `DELETE /queue/history/{id}/`, `DELETE /queue/history/` (clear all),
   or `POST /queue/history/{id}/play/` to replay immediately.
9. Curated mix: `GET /playlists/gym/` then `POST /playlists/gym/enqueue/` (optional `video_ids`).

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
| `music.view` | Open FloorCue / read queue; receive pending-request inbox + FCM |
| `music.update` | Play, skip, complete, approve, settings, block/unblock |

## Honest limits

Keyword + badge filtering catches many age-gated videos, not all. Official YouTube Music /
Spotify remote control is out of scope.
