from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from attendance.bridge_pull import parse_bridge_timestamp, pull_once

DHAKA = ZoneInfo("Asia/Dhaka")


def test_parse_bridge_timestamp_naive_is_dhaka():
    dt = parse_bridge_timestamp("2026-11-22T18:42:21")
    assert dt is not None
    assert dt.tzinfo == DHAKA
    assert dt.hour == 18 and dt.minute == 42


def test_parse_bridge_timestamp_zulu():
    dt = parse_bridge_timestamp("2026-11-22T12:42:21Z")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 0


@pytest.mark.django_db
def test_pull_once_records_member_punch(member, staff, plan, settings):
    from payments.services import receive_cash

    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    member.member_profile.profile_complete = True
    member.member_profile.save()
    receive_cash(staff, member.member_profile, plan.pk)

    rows = [
        {
            "user_id": member.member_profile.member_id,
            "timestamp": "2026-11-22T18:42:21",
            "state": 1,
            "type": 0,
        }
    ]
    with patch("attendance.bridge_pull.bridge.list_attendance", return_value=rows):
        stats = pull_once(lookback_days=7)

    assert stats["fetched"] == 1
    assert stats["recorded"] == 1
    assert stats["errors"] == 0
    visit = member.member_profile.check_ins.get(check_in_date="2026-11-22")
    assert visit.punches.count() == 1
    punch = visit.punches.get()
    assert punch.punched_at.astimezone(DHAKA).hour == 18


@pytest.mark.django_db
def test_pull_once_skips_unknown_and_unpaid(member, settings):
    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    rows = [
        {"user_id": "PF-NOPE", "timestamp": "2026-11-22T10:00:00", "state": 1, "type": 0},
        {
            "user_id": member.member_profile.member_id,
            "timestamp": "2026-11-22T11:00:00",
            "state": 1,
            "type": 0,
        },
    ]
    with patch("attendance.bridge_pull.bridge.list_attendance", return_value=rows):
        stats = pull_once(lookback_days=7)

    assert stats["fetched"] == 2
    assert stats["recorded"] == 0
    assert stats["skipped"] == 2
    assert not member.member_profile.check_ins.exists()


@pytest.mark.django_db
def test_pull_bridge_attendance_command(member, staff, plan, settings, capsys):
    from payments.services import receive_cash

    settings.ZKTECO_BRIDGE_URL = "http://bridge.test"
    settings.ZKTECO_BRIDGE_KEY = "test-key"
    member.member_profile.profile_complete = True
    member.member_profile.save()
    receive_cash(staff, member.member_profile, plan.pk)

    rows = [
        {
            "user_id": member.member_profile.member_id,
            "timestamp": "2026-11-22T14:22:59",
            "state": 1,
            "type": 0,
        }
    ]
    with patch("attendance.bridge_pull.bridge.list_attendance", return_value=rows):
        call_command("pull_bridge_attendance", "--lookback-days", "3")

    out = capsys.readouterr().out
    assert "recorded=1" in out
    assert member.member_profile.check_ins.filter(check_in_date="2026-11-22").exists()
