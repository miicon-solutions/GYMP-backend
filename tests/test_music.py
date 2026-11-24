import pytest
from rest_framework.test import APIClient


def client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _stub_meta(monkeypatch):
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
            "age_restricted": False,
        },
    )


def _disable_approval(staff_client):
    res = staff_client.post(
        "/api/v1/music/settings/",
        {"require_approval": False, "is_enabled": True},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["require_approval"] is False


@pytest.mark.django_db
def test_user_can_queue_max_three_songs_fifo_without_autoplay(
    member, other_member, staff, monkeypatch
):
    _stub_meta(monkeypatch)
    m1 = client_for(member)
    m2 = client_for(other_member)
    staff_client = client_for(staff)
    _disable_approval(staff_client)

    r1 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4"},
        format="json",
    )
    assert r1.status_code == 201
    assert r1.data["item"]["video_id"] == "eVTXPUF4Oz4"
    assert r1.data["item"]["status"] == "queued"
    assert r1.data["queue_state"]["now_playing"] is None
    assert r1.data["queue_state"]["user_active_count"] == 1
    assert r1.data["queue_state"]["remaining_slots"] == 2

    r2 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://youtu.be/kXYiU_JCYtU"},
        format="json",
    )
    assert r2.status_code == 201
    assert r2.data["item"]["status"] == "queued"
    assert r2.data["queue_state"]["user_active_count"] == 2

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
    assert r3.data["queue_state"]["remaining_slots"] == 0

    r4 = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=Yhyp-_hX2s0"},
        format="json",
    )
    assert r4.status_code == 400
    assert "3 songs" in str(r4.data)

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
    assert r5.data["queue_state"]["now_playing"] is None

    # GET must not auto-start playback
    get_res = m1.get("/api/v1/music/queue/")
    assert get_res.status_code == 200
    assert get_res.data["now_playing"] is None

    # Staff play starts the head
    play_res = staff_client.post("/api/v1/music/queue/play/")
    assert play_res.status_code == 200
    assert play_res.data["now_playing"]["video_id"] == "eVTXPUF4Oz4"
    assert play_res.data["now_playing"]["status"] == "playing"
    assert play_res.data["is_playback_active"] is True

    # Pause keeps now_playing but clears speaker-active for member UI
    pause_res = staff_client.post(
        "/api/v1/music/queue/playback/",
        {"is_playback_active": False},
        format="json",
    )
    assert pause_res.status_code == 200
    assert pause_res.data["now_playing"]["video_id"] == "eVTXPUF4Oz4"
    assert pause_res.data["is_playback_active"] is False
    member_view = m1.get("/api/v1/music/queue/")
    assert member_view.status_code == 200
    assert member_view.data["is_playback_active"] is False
    assert member_view.data["now_playing"]["video_id"] == "eVTXPUF4Oz4"

    resume_speaker = staff_client.post(
        "/api/v1/music/queue/playback/",
        {"is_playback_active": True},
        format="json",
    )
    assert resume_speaker.status_code == 200
    assert resume_speaker.data["is_playback_active"] is True
    assert m1.post(
        "/api/v1/music/queue/playback/",
        {"is_playback_active": False},
        format="json",
    ).status_code == 403


@pytest.mark.django_db
def test_staff_controls_skip_remove_play_and_toggle(member, other_member, staff, monkeypatch):
    _stub_meta(monkeypatch)
    m1 = client_for(member)
    m2 = client_for(other_member)
    staff_client = client_for(staff)
    _disable_approval(staff_client)

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

    assert m1.post("/api/v1/music/queue/play/").status_code == 403
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
    assert m1.delete(f"/api/v1/music/queue/{s2['id']}/").status_code == 403

    play_res = staff_client.post("/api/v1/music/queue/play/")
    assert play_res.status_code == 200
    assert str(play_res.data["now_playing"]["id"]) == str(s1["id"])

    skip_res = staff_client.post("/api/v1/music/queue/skip/")
    assert skip_res.status_code == 200
    assert str(skip_res.data["now_playing"]["id"]) == str(s2["id"])
    assert skip_res.data["now_playing"]["status"] == "playing"
    # Queue lists upcoming only — now-playing is not duplicated.
    assert [str(item["id"]) for item in skip_res.data["queue"]] == [str(s3["id"])]

    rem_res = staff_client.delete(f"/api/v1/music/queue/{s2['id']}/")
    assert rem_res.status_code == 200
    assert str(rem_res.data["now_playing"]["id"]) == str(s3["id"])

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

    on_res = staff_client.post("/api/v1/music/settings/", {"is_enabled": True}, format="json")
    assert on_res.status_code == 200
    assert on_res.data["is_enabled"] is True
    # Re-enable does not auto-start
    assert on_res.data["now_playing"] is None
    assert str(on_res.data["queue"][0]["id"]) == str(s3["id"])

    resume = staff_client.post("/api/v1/music/queue/play/")
    assert resume.status_code == 200
    assert str(resume.data["now_playing"]["id"]) == str(s3["id"])

    complete = staff_client.post(
        "/api/v1/music/queue/complete/", {"item_id": str(s3["id"])}, format="json"
    )
    assert complete.status_code == 200
    assert complete.data["now_playing"] is None
    assert str(s3["id"]) in [str(h["id"]) for h in complete.data["history"] if h["status"] == "played"]


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
def test_default_approval_inbox_play_block_and_age_restriction(
    member, other_member, staff, monkeypatch
):
    _stub_meta(monkeypatch)
    m1 = client_for(member)
    m2 = client_for(other_member)
    staff_client = client_for(staff)

    # Default require_approval is True (inbox-first)
    state = staff_client.get("/api/v1/music/queue/").data
    assert state["require_approval"] is True

    age_res = m1.post(
        "/api/v1/music/queue/",
        {
            "youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4",
            "title": "Explicit 18+ NSFW Music Video",
        },
        format="json",
    )
    assert age_res.status_code == 400
    assert "18+" in str(age_res.data).lower() or "age-restricted" in str(age_res.data).lower()

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
    assert len(add_res.data["queue_state"]["queue"]) == 0

    # Approve → queued, still not playing
    app_res = staff_client.post(f"/api/v1/music/queue/{item_id}/approve/")
    assert app_res.status_code == 200
    assert app_res.data["now_playing"] is None
    assert str(app_res.data["queue"][0]["id"]) == str(item_id)
    assert app_res.data["queue"][0]["status"] == "queued"
    assert len(app_res.data["pending_approval"]) == 0

    # Member cannot approve
    assert m2.post(f"/api/v1/music/queue/{item_id}/approve/").status_code == 403

    play_res = staff_client.post("/api/v1/music/queue/play/")
    assert play_res.status_code == 200
    assert str(play_res.data["now_playing"]["id"]) == str(item_id)

    # Report / restore still work
    rep_res = m2.post(
        f"/api/v1/music/queue/{item_id}/report/",
        {"reason": "Too loud / wrong genre"},
        format="json",
    )
    assert rep_res.status_code == 200
    assert rep_res.data["now_playing"] is None

    rest_res = staff_client.post(f"/api/v1/music/queue/{item_id}/restore/")
    assert rest_res.status_code == 200
    assert rest_res.data["now_playing"] is None
    assert str(rest_res.data["queue"][0]["id"]) == str(item_id)

    play_again = staff_client.post("/api/v1/music/queue/play/")
    assert str(play_again.data["now_playing"]["id"]) == str(item_id)

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

    unblk_res = staff_client.delete(f"/api/v1/music/blocks/{member.id}/")
    assert unblk_res.status_code == 200
    assert len(unblk_res.data["blocked_users"]) == 0


@pytest.mark.django_db
def test_reject_pending_via_delete(member, staff, monkeypatch):
    _stub_meta(monkeypatch)
    m1 = client_for(member)
    staff_client = client_for(staff)

    add_res = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4", "title": "Pending"},
        format="json",
    )
    assert add_res.status_code == 201
    item_id = add_res.data["item"]["id"]
    assert add_res.data["item"]["status"] == "pending_approval"

    reject = staff_client.delete(f"/api/v1/music/queue/{item_id}/")
    assert reject.status_code == 200
    assert len(reject.data["pending_approval"]) == 0
    assert reject.data["now_playing"] is None


@pytest.mark.django_db
def test_staff_can_clear_history_item_and_all(member, staff, monkeypatch):
    _stub_meta(monkeypatch)
    m1 = client_for(member)
    staff_client = client_for(staff)
    _disable_approval(staff_client)

    a = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4", "title": "A"},
        format="json",
    ).data["item"]
    b = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=kXYiU_JCYtU", "title": "B"},
        format="json",
    ).data["item"]

    assert staff_client.post("/api/v1/music/queue/play/").status_code == 200
    assert staff_client.post(
        "/api/v1/music/queue/complete/", {"item_id": str(a["id"])}, format="json"
    ).status_code == 200
    assert staff_client.post(
        "/api/v1/music/queue/complete/", {"item_id": str(b["id"])}, format="json"
    ).status_code == 200

    hist = staff_client.get("/api/v1/music/queue/").data["history"]
    assert {str(h["id"]) for h in hist} >= {str(a["id"]), str(b["id"])}
    assert all(h["can_remove"] for h in hist if str(h["id"]) in {str(a["id"]), str(b["id"])})

    assert m1.delete(f"/api/v1/music/queue/history/{a['id']}/").status_code == 403

    one = staff_client.delete(f"/api/v1/music/queue/history/{a['id']}/")
    assert one.status_code == 200
    assert str(a["id"]) not in [str(h["id"]) for h in one.data["history"]]
    assert str(b["id"]) in [str(h["id"]) for h in one.data["history"]]

    cleared = staff_client.delete("/api/v1/music/queue/history/")
    assert cleared.status_code == 200
    assert cleared.data["history"] == []


@pytest.mark.django_db
def test_staff_can_replay_history_item(member, staff, monkeypatch):
    _stub_meta(monkeypatch)
    m1 = client_for(member)
    staff_client = client_for(staff)
    _disable_approval(staff_client)

    a = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4", "title": "A"},
        format="json",
    ).data["item"]
    b = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=kXYiU_JCYtU", "title": "B"},
        format="json",
    ).data["item"]

    assert staff_client.post("/api/v1/music/queue/play/").status_code == 200
    assert staff_client.post(
        "/api/v1/music/queue/complete/", {"item_id": str(a["id"])}, format="json"
    ).status_code == 200
    assert staff_client.get("/api/v1/music/queue/").data["now_playing"]["video_id"] == "kXYiU_JCYtU"

    replay = staff_client.post(f"/api/v1/music/queue/history/{a['id']}/play/")
    assert replay.status_code == 200
    assert replay.data["now_playing"]["video_id"] == "eVTXPUF4Oz4"
    assert replay.data["now_playing"]["status"] == "playing"
    # Previous now-playing was interrupted into history as skipped.
    assert str(b["id"]) in [
        str(h["id"]) for h in replay.data["history"] if h["status"] == "skipped"
    ]
    assert m1.post(f"/api/v1/music/queue/history/{a['id']}/play/").status_code == 403


@pytest.mark.django_db
def test_staff_can_reorder_and_play_specific_queue_item(member, staff, monkeypatch):
    _stub_meta(monkeypatch)
    m1 = client_for(member)
    staff_client = client_for(staff)
    _disable_approval(staff_client)

    a = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=eVTXPUF4Oz4", "title": "A"},
        format="json",
    ).data["item"]
    b = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=kXYiU_JCYtU", "title": "B"},
        format="json",
    ).data["item"]
    c = m1.post(
        "/api/v1/music/queue/",
        {"youtube_url": "https://www.youtube.com/watch?v=fJ9rUzIMcZQ", "title": "C"},
        format="json",
    ).data["item"]

    # Drag C to the front of the queue.
    reordered = staff_client.post(
        "/api/v1/music/queue/reorder/",
        {"item_ids": [str(c["id"]), str(a["id"]), str(b["id"])]},
        format="json",
    )
    assert reordered.status_code == 200
    assert [item["video_id"] for item in reordered.data["queue"]] == [
        "fJ9rUzIMcZQ",
        "eVTXPUF4Oz4",
        "kXYiU_JCYtU",
    ]

    assert staff_client.post("/api/v1/music/queue/play/").status_code == 200
    assert staff_client.get("/api/v1/music/queue/").data["now_playing"]["video_id"] == "fJ9rUzIMcZQ"

    # Tap B while C is playing → B plays; A rotates after (was ahead of B).
    play_b = staff_client.post(f"/api/v1/music/queue/{b['id']}/play/")
    assert play_b.status_code == 200
    assert play_b.data["now_playing"]["video_id"] == "kXYiU_JCYtU"
    assert [item["video_id"] for item in play_b.data["queue"]] == ["eVTXPUF4Oz4"]
    assert m1.post(f"/api/v1/music/queue/{a['id']}/play/").status_code == 403


@pytest.mark.django_db
def test_gym_playlist_list_and_enqueue(staff, monkeypatch):
    _stub_meta(monkeypatch)
    staff_client = client_for(staff)

    listing = staff_client.get("/api/v1/music/playlists/gym/")
    assert listing.status_code == 200
    assert listing.data["id"] == "gym_floor"
    assert len(listing.data["tracks"]) >= 8
    first_id = listing.data["tracks"][0]["video_id"]

    enq = staff_client.post(
        "/api/v1/music/playlists/gym/enqueue/",
        {"video_ids": [first_id, listing.data["tracks"][1]["video_id"]]},
        format="json",
    )
    assert enq.status_code == 200
    assert enq.data["added"] == 2
    assert enq.data["skipped_existing"] == 0
    assert enq.data["queue_state"]["now_playing"] is None
    assert len(enq.data["queue_state"]["queue"]) == 2

    again = staff_client.post(
        "/api/v1/music/playlists/gym/enqueue/",
        {"video_ids": [first_id]},
        format="json",
    )
    assert again.status_code == 200
    assert again.data["added"] == 0
    assert again.data["skipped_existing"] == 1

    full = staff_client.post("/api/v1/music/playlists/gym/enqueue/", {}, format="json")
    assert full.status_code == 200
    assert full.data["added"] >= 1
    # Staff playlist bypasses the usual 3-song per-user cap.
    assert len(full.data["queue_state"]["queue"]) > 3
