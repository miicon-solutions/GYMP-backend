"""Curated FloorCue playlists (static catalog — no DB rows)."""

# High-energy workout staples that work well on a gym floor (official / popular uploads).
# Titles are display hints; enqueue resolves live metadata via oEmbed when possible.
GYM_FLOOR_PLAYLIST = (
    {
        "video_id": "btPJPFnesV4",
        "title": "Survivor - Eye of the Tiger (Official HD Video)",
        "channel_title": "SurvivorVEVO",
    },
    {
        "video_id": "Yhyp-_hX2s0",
        "title": "Eminem - Lose Yourself",
        "channel_title": "EminemMusic",
    },
    {
        "video_id": "7wtfhZwyrcc",
        "title": "Imagine Dragons - Believer",
        "channel_title": "ImagineDragonsVEVO",
    },
    {
        "video_id": "PsO6ZnUZI0g",
        "title": "Kanye West - Stronger",
        "channel_title": "KanyeWestVEVO",
    },
    {
        "video_id": "v2AC41dglnM",
        "title": "AC/DC - Thunderstruck (Official Video)",
        "channel_title": "acdcVEVO",
    },
    {
        "video_id": "JRfuAukYTKg",
        "title": "David Guetta ft. Sia - Titanium (Official Video)",
        "channel_title": "David Guetta",
    },
    {
        "video_id": "_ovdm2yX4MA",
        "title": "Avicii - Levels",
        "channel_title": "AviciiOfficialVEVO",
    },
    {
        "video_id": "4NRXx6U8ABQ",
        "title": "The Weeknd - Blinding Lights (Official Video)",
        "channel_title": "TheWeekndVEVO",
    },
    {
        "video_id": "oygrmJFKYZY",
        "title": "Dua Lipa - Don't Start Now (Official Music Video)",
        "channel_title": "Dua Lipa",
    },
    {
        "video_id": "2vjPBrBU-TM",
        "title": "Macklemore & Ryan Lewis - Can't Hold Us ft. Ray Dalton",
        "channel_title": "Macklemore LLC",
    },
    {
        "video_id": "fKopy74weus",
        "title": "Imagine Dragons - Thunder",
        "channel_title": "ImagineDragonsVEVO",
    },
    {
        "video_id": "hTWKbfoikeg",
        "title": "Nirvana - Smells Like Teen Spirit (Official Music Video)",
        "channel_title": "Nirvana",
    },
)

GYM_FLOOR_PLAYLIST_ID = "gym_floor"
GYM_FLOOR_PLAYLIST_TITLE = "Gym Floor Energy"
GYM_FLOOR_PLAYLIST_DESCRIPTION = (
    "Pre-built high-energy workout mix — queue it when the floor needs a boost."
)


def serialize_gym_playlist() -> dict:
    tracks = []
    for entry in GYM_FLOOR_PLAYLIST:
        video_id = entry["video_id"]
        tracks.append(
            {
                "video_id": video_id,
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                "title": entry["title"],
                "channel_title": entry.get("channel_title", ""),
                "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "duration_text": "",
                "duration_seconds": None,
            }
        )
    return {
        "id": GYM_FLOOR_PLAYLIST_ID,
        "title": GYM_FLOOR_PLAYLIST_TITLE,
        "description": GYM_FLOOR_PLAYLIST_DESCRIPTION,
        "tracks": tracks,
    }
