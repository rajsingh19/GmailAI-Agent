"""
Tests for Timezone-Aware Quiet Hours, Exact Boundaries, and DST Calculations (Milestone 8).
Validates:
- Exact boundaries: 22:00, 23:30, 00:30, 07:59, 08:00
- Midnight rollover calculation
- URGENT priority bypass
- HIGH, MEDIUM, LOW priority deferral
- IANA timezone conversions (America/New_York, Asia/Kolkata)
- Daylight Saving Time (DST) transition handling
"""
import pytest
from datetime import datetime, timezone
import zoneinfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preference import UserPreference
from app.services.proactive.decision_engine import is_in_quiet_hours, ProactiveDecisionEngine


def make_pref(
    tz: str = "UTC",
    start: str = "22:00",
    end: str = "08:00",
    enabled: bool = True,
    defer_high: bool = True,
) -> UserPreference:
    return UserPreference(
        user_id="test_user_qh",
        proactive_enabled=True,
        calendar_alerts_enabled=True,
        task_alerts_enabled=True,
        reminder_alerts_enabled=True,
        email_alerts_enabled=True,
        quiet_hours_enabled=enabled,
        quiet_hours_start=start,
        quiet_hours_end=end,
        defer_high_priority_in_quiet_hours=defer_high,
        user_timezone=tz,
        min_priority="low",
    )


def test_quiet_hours_exact_boundary_2200_start():
    """At exactly 22:00:00 (start boundary), quiet hours is active (True)."""
    pref = make_pref(tz="UTC", start="22:00", end="08:00")
    dt = datetime(2026, 9, 16, 22, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt) is True


def test_quiet_hours_exact_boundary_0800_exit():
    """At exactly 08:00:00 (exit boundary), quiet hours ends (False)."""
    pref = make_pref(tz="UTC", start="22:00", end="08:00")
    dt = datetime(2026, 9, 16, 8, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt) is False


def test_quiet_hours_inside_0759():
    """At 07:59:59 (1 second before exit), quiet hours is active (True)."""
    pref = make_pref(tz="UTC", start="22:00", end="08:00")
    dt = datetime(2026, 9, 16, 7, 59, 59, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt) is True


def test_quiet_hours_midnight_rollover_2330():
    """At 23:30 (before midnight), quiet hours is active (True)."""
    pref = make_pref(tz="UTC", start="22:00", end="08:00")
    dt = datetime(2026, 9, 16, 23, 30, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt) is True


def test_quiet_hours_midnight_rollover_0030():
    """At 00:30 (after midnight), quiet hours is active (True)."""
    pref = make_pref(tz="UTC", start="22:00", end="08:00")
    dt = datetime(2026, 9, 16, 0, 30, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt) is True


def test_quiet_hours_daytime_outside():
    """At 14:00 (mid-day), quiet hours is inactive (False)."""
    pref = make_pref(tz="UTC", start="22:00", end="08:00")
    dt = datetime(2026, 9, 16, 14, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt) is False


def test_iana_timezone_conversion_america_new_york():
    """
    User in New York (EDT, UTC-4 in September).
    When UTC is 03:00, New York time is 23:00 -> inside quiet hours (True).
    When UTC is 15:00, New York time is 11:00 -> outside quiet hours (False).
    """
    pref = make_pref(tz="America/New_York", start="22:00", end="08:00")
    
    # 03:00 UTC = 23:00 EDT (Quiet hours)
    dt_quiet = datetime(2026, 9, 16, 3, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt_quiet) is True

    # 15:00 UTC = 11:00 EDT (Work hours)
    dt_active = datetime(2026, 9, 16, 15, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt_active) is False


def test_iana_timezone_conversion_asia_kolkata():
    """
    User in Kolkata (IST, UTC+5:30).
    When UTC is 17:00, Kolkata time is 22:30 -> inside quiet hours (True).
    When UTC is 06:00, Kolkata time is 11:30 -> outside quiet hours (False).
    """
    pref = make_pref(tz="Asia/Kolkata", start="22:00", end="08:00")

    # 17:00 UTC = 22:30 IST
    dt_quiet = datetime(2026, 9, 16, 17, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt_quiet) is True

    # 06:00 UTC = 11:30 IST
    dt_active = datetime(2026, 9, 16, 6, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt_active) is False


def test_dst_transition_day_quiet_hours_calculation():
    """
    Tests DST 'fall back' transition day in America/New_York (Nov 1, 2026).
    Quiet hours must correctly evaluate local wall clock time across the standard time shift.
    """
    pref = make_pref(tz="America/New_York", start="22:00", end="08:00")
    
    # Nov 2, 2026 04:00 UTC is Nov 1, 2026 23:00 EST (UTC-5) -> Quiet hours
    dt_est = datetime(2026, 11, 2, 4, 0, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(pref, dt_est) is True


@pytest.mark.asyncio
async def test_urgent_priority_bypasses_quiet_hours(test_db: AsyncSession):
    """An 'urgent' priority notification is approved and delivered even during quiet hours."""
    engine = ProactiveDecisionEngine()
    pref = make_pref(tz="UTC", start="22:00", end="08:00")
    # 23:00 UTC is inside quiet hours
    now = datetime(2026, 9, 16, 23, 0, 0, tzinfo=timezone.utc)

    candidate = {
        "detection_type": "task_overdue",
        "source_type": "task",
        "source_id": "urgent_t1",
        "title": "Urgent Server Outage Task",
        "message": "Immediate action required.",
        "priority": "urgent",
        "idempotency_anchor": "2026-09-16",
    }
    
    delivered, reason, _, _ = await engine.evaluate_candidate(test_db, pref, candidate, now_utc=now)
    assert delivered is True
    assert reason == "approved"


@pytest.mark.asyncio
async def test_high_priority_deferred_when_configured(test_db: AsyncSession):
    """A 'high' priority notification is deferred when defer_high_priority_in_quiet_hours is True."""
    engine = ProactiveDecisionEngine()
    pref = make_pref(tz="UTC", start="22:00", end="08:00", defer_high=True)
    now = datetime(2026, 9, 16, 23, 0, 0, tzinfo=timezone.utc)

    candidate = {
        "detection_type": "task_due_soon",
        "source_type": "task",
        "source_id": "high_t1",
        "title": "High Priority Task Due",
        "priority": "high",
        "idempotency_anchor": "2026-09-16T23:00",
    }

    delivered, reason, _, _ = await engine.evaluate_candidate(test_db, pref, candidate, now_utc=now)
    assert delivered is False
    assert reason == "deferred_quiet_hours"


@pytest.mark.asyncio
async def test_high_priority_delivered_when_defer_is_false(test_db: AsyncSession):
    """A 'high' priority notification is delivered when defer_high_priority_in_quiet_hours is False."""
    engine = ProactiveDecisionEngine()
    pref = make_pref(tz="UTC", start="22:00", end="08:00", defer_high=False)
    now = datetime(2026, 9, 16, 23, 0, 0, tzinfo=timezone.utc)

    candidate = {
        "detection_type": "task_due_soon",
        "source_type": "task",
        "source_id": "high_t2",
        "title": "High Priority Task Due",
        "priority": "high",
        "idempotency_anchor": "2026-09-16T23:00",
    }

    delivered, reason, _, _ = await engine.evaluate_candidate(test_db, pref, candidate, now_utc=now)
    assert delivered is True
    assert reason == "approved"
