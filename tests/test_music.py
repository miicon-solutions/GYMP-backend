import pytest
from rest_framework.test import APIClient


def client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.mark.django_db
def test_user_can_queue_max_three_songs_and_plays_in_order(member, other_member, monkeypatch):
    monkeypatch.setattr(
        "music.services.resolve_youtube_metadata",
        lambda vid: {
            "video_id": vid,
            "youtube_url": f"https://www.youtube.com/watch?v={vid}",
            "title": f"Track {vid}",
            "channel_title": "Gym Artist",
            "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "duration_text": "3:30",
            "duration_seconds": 210,
        },
    )

    m1 = client_for(member)
    m2 = client_for(other_member)

    # Member 1 adds 3 songs using various YouTube link formats
    r1 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4"},
        format="json",
    )
    assert r1.status_code == 201
    assert r1.data["item"]["video_id"] == "eVTXPUF4Oz4"
    assert r1.data["item"]["status"] == "playing"
    assert r1.data["queue_state"]["user_active_count"] == 1
    assert r1.data["queue_state"]["remaining_slots"] == 2

    r2 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://youtu.be/kXYiU_JCYtU"},
        format="json",
    )
    assert r2.status_code == 201
    assert r2.data["item"]["video_id"] == "kXYiU_JCYtU"
    assert r2.data["item"]["status"] == "queued"
    assert r2.data["queue_state"]["user_active_count"] == 2
    assert r2.data["queue_state"]["remaining_slots"] == 1

    r3 = m1.post(
        "/api/v1/music/queue/",
        {
            "youtube_url": "https://music.youtube.com/watch?v=btPJPFnesV4",
            "title": "Eye of the Tiger",
            "channel_title": "Survivor",
        },
        format="json",
    )
    assert r3.status_code == 201
    assert r3.data["item"]["status"] == "queued"
    assert r3.data["queue_state"]["user_active_count"] == 3
    assert r3.data["queue_state"]["remaining_slots"] == 0

    # 4th song by Member 1 must be rejected (max 3 per user)
    r4 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=Yhyp-_hX2s0"},
        format="json",
    )
    assert r4.status_code == 400
    assert "3 songs" in str(r4.data)

    # Member 2 can still add their own song and it goes to position 4 in FIFO order
    r5 = m2.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=v2AC41dglnM"},
        format="json",
    )
    assert r5.status_code == 201
    queue = r5.data["queue_state"]["queue"]
    assert [item["video_id"] for item in queue] == [
        "eVTXPUF4Oz4",
        "kXYiU_JCYtU",
        "btPJPFnesV4",
        "v2AC41dglnM",
    ]
    assert [item["position"] for item in queue] == [1, 2, 3, 4]


@pytest.mark.django_db
def test_staff_controls_skip_remove_and_toggle_queue_system(member, other_member, staff):
    m1 = client_for(member)
    m2 = client_for(other_member)
    staff_client = client_for(staff)

    s1 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4", "title": "Song 1"},
        format="json",
    ).data["item"]
    s2 = m2.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=kXYiU_JCYtU", "title": "Song 2"},
        format="json",
    ).data["item"]
    s3 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=btPJPFnesV4", "title": "Song 3"},
        format="json",
    ).data["item"]

    # Member cannot skip, complete playback, or toggle settings
    assert m1.post("/api/v1/music/queue/skip/").status_code == 403
    assert (
        m1.post(
            "/api/v1/music/queue/complete/", {"item_id": str(s1["id"])}, format="json"
        ).status_code
        == 403
    )
    assert (
        m1.post("/api/v1/music/settings/", {"is_enabled": False}, format="json").status_code == 403
    )

    # Member 1 cannot remove Member 2's song
    assert m1.delete(f"/api/v1/music/queue/{s2['id']}/").status_code == 403

    # Staff skips Song 1 -> Song 2 becomes now_playing
    skip_res = staff_client.post("/api/v1/music/queue/skip/")
    assert skip_res.status_code == 200
    assert str(skip_res.data["now_playing"]["id"]) == str(s2["id"])
    assert skip_res.data["now_playing"]["status"] == "playing"
    assert [str(item["id"]) for item in skip_res.data["queue"]] == [str(s2["id"]), str(s3["id"])]
    assert str(s1["id"]) in [
        str(h["id"]) for h in skip_res.data["history"] if h["status"] == "skipped"
    ]

    # Staff removes Song 2 -> Song 3 becomes now_playing
    rem_res = staff_client.delete(f"/api/v1/music/queue/{s2['id']}/")
    assert rem_res.status_code == 200
    assert str(rem_res.data["now_playing"]["id"]) == str(s3["id"])

    # Staff turns OFF the queue system -> now_playing stops, new additions blocked
    off_res = staff_client.post("/api/v1/music/settings/", {"is_enabled": False}, format="json")
    assert off_res.status_code == 200
    assert off_res.data["is_enabled"] is False
    assert off_res.data["now_playing"] is None

    blocked = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=v2AC41dglnM", "title": "Song 4"},
        format="json",
    )
    assert blocked.status_code == 400
    assert "turned off" in str(blocked.data).lower()

    # Staff re-enables the queue system -> Song 3 resumes playing
    on_res = staff_client.post("/api/v1/music/settings/", {"is_enabled": True}, format="json")
    assert on_res.status_code == 200
    assert on_res.data["is_enabled"] is True
    assert str(on_res.data["now_playing"]["id"]) == str(s3["id"])
    assert on_res.data["now_playing"]["status"] == "playing"


@pytest.mark.django_db
def test_youtube_search_and_link_resolution(member, monkeypatch):
    m1 = client_for(member)

    class DummyPostResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "contents": {
                    "twoColumnSearchResultsRenderer": {
                        "PrimaryContents": {
                            "sectionListRenderer": {
                                "contents": [
                                    {
                                        "itemSectionRenderer": {
                                            "contents": [
                                                {
                                                    "videoRenderer": {
                                                        "videoId": "eVTXPUF4Oz4",
                                                        "title": {
                                                            "runs": [
                                                                {"text": "Linkin Park - In The End"}
                                                            ]
                                                        },
                                                        "ownerText": {
                                                            "runs": [{"text": "Linkin Park"}]
                                                        },
                                                        "lengthText": {"simpleText": "3:37"},
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
            }

    monkeypatch.setattr("music.services.httpx.post", lambda *a, **kw: DummyPostResponse())

    res = m1.get("/api/v1/music/search/?q=Linkin+Park")
    assert res.status_code == 200
    assert len(res.data["results"]) >= 1
    first = res.data["results"][0]
    assert first["video_id"] == "eVTXPUF4Oz4"
    assert first["title"] == "Linkin Park - In The End"
    assert first["duration_seconds"] == 217


@pytest.mark.django_db
def test_admin_music_approval_reporting_user_blocking_and_age_restriction(
    member, other_member, staff
):
    m1 = client_for(member)
    m2 = client_for(other_member)
    staff_client = client_for(staff)

    # 1. Admin turns on require_approval and sets max_songs_per_user to 2 (Suggestion 11)
    s_res = staff_client.post(
        "/api/v1/music/settings/",
        {"is_enabled": True, "require_approval": True, "max_songs_per_user": 2},
        format="json",
    )
    assert s_res.status_code == 200
    assert s_res.data["require_approval"] is True
    assert s_res.data["max_songs_per_user"] == 2

    # 2. Age-restricted video is automatically blocked
    age_res = m1.post(
        "/api/v1/music/queue/",
        {
            "youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4",
            "title": "Explicit 18+ NSFW Music Video",
        },
        format="json",
    )
    assert age_res.status_code == 400
    assert "age-restricted" in str(age_res.data).lower()

    # 3. Member 1 adds a valid song -> waits in pending_approval (not playing yet!)
    add_res = m1.post(
        "/api/v1/music/queue/",
        {
            "youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4",
            "title": "In The End",
        },
        format="json",
    )
    assert add_res.status_code == 201
    item_id = add_res.data["item"]["id"]
    assert add_res.data["item"]["status"] == "pending_approval"
    assert add_res.data["queue_state"]["now_playing"] is None
    assert len(add_res.data["queue_state"]["pending_approval"]) == 1

    # 4. Admin approves the song -> enters active queue and starts playing!
    app_res = staff_client.post(f"/api/v1/music/queue/{item_id}/approve/")
    assert app_res.status_code == 200
    assert str(app_res.data["now_playing"]["id"]) == str(item_id)
    assert app_res.data["now_playing"]["status"] == "playing"

    # 5. Member 2 reports the song -> hides it from queue until admin checks it
    rep_res = m2.post(
        f"/api/v1/music/queue/{item_id}/report/",
        {"reason": "Too loud / wrong genre"},
        format="json",
    )
    assert rep_res.status_code == 200
    assert rep_res.data["now_playing"] is None
    assert len(rep_res.data["queue"]) == 0

    # Admin sees it in reported_items and restores it
    admin_state = staff_client.get("/api/v1/music/queue/").data
    assert len(admin_state["reported_items"]) == 1
    rest_res = staff_client.post(f"/api/v1/music/queue/{item_id}/restore/")
    assert rest_res.status_code == 200
    assert str(rest_res.data["now_playing"]["id"]) == str(item_id)

    # 6. Admin blocks Member 1 -> removes their active songs and prevents adding more
    blk_res = staff_client.post(
        "/api/v1/music/blocks/",
        {"user_id": str(member.id), "reason": "Spamming queue"},
        format="json",
    )
    assert blk_res.status_code == 200
    assert blk_res.data["now_playing"] is None
    assert len(blk_res.data["blocked_users"]) == 1

    denied = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=kXYiU_JCYtU", "title": "Numb"},
        format="json",
    )
    assert denied.status_code == 403

    # Admin unblocks Member 1
    unblk_res = staff_client.delete(f"/api/v1/music/blocks/{member.id}/")
    assert unblk_res.status_code == 200
    assert len(unblk_res.data["blocked_users"]) == 0

