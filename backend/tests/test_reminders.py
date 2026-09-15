"""
Test Suite for Reminder System (Milestone 5).
Validates:
- Authentication requirements (HTTP 401)
- One-time & recurring reminder scheduling
- Task ownership link validation
- Snooze durations & custom snooze
- Cancellation semantics
- Strict multi-user isolation
- Timezone & DST safety (America/New_York, Asia/Kolkata, UTC)
"""
from datetime import datetime, timezone, timedelta
import zoneinfo
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.models.task import Task
from app.services.reminder_service import compute_next_occurrence, parse_snooze_duration


async def create_test_user(test_db: AsyncSession, email: str = "reminder_user@example.com") -> User:
    user = User(email=email, full_name="Reminder Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_reminder_endpoints_require_authentication(async_client: AsyncClient):
    """All reminder endpoints must return 401 when unauthenticated."""
    assert (await async_client.get("/api/v1/reminders")).status_code == 401
    assert (await async_client.post("/api/v1/reminders", json={"title": "Test", "remind_at": "2026-09-20T10:00:00Z"})).status_code == 401
    assert (await async_client.get("/api/v1/reminders/rem-123")).status_code == 401
    assert (await async_client.patch("/api/v1/reminders/rem-123", json={"title": "Updated"})).status_code == 401
    assert (await async_client.post("/api/v1/reminders/rem-123/snooze", json={"duration": "15m"})).status_code == 401
    assert (await async_client.post("/api/v1/reminders/rem-123/cancel")).status_code == 401
    assert (await async_client.delete("/api/v1/reminders/rem-123")).status_code == 401


@pytest.mark.asyncio
async def test_create_one_time_reminder_success(async_client: AsyncClient, test_db: AsyncSession):
    """Create one-time reminder with timezone-aware datetime."""
    user = await create_test_user(test_db, "onetime@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    resp = await async_client.post(
        "/api/v1/reminders",
        json={
            "title": "Call dentist",
            "message": "Appointment at 3 PM",
            "remind_at": trigger_dt,
            "timezone": "America/New_York",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Call dentist"
    assert data["status"] == "scheduled"
    assert data["recurrence_rule"] is None
    assert data["next_trigger_at"] is not None
    assert data["user_id"] == user.id


@pytest.mark.asyncio
async def test_create_recurring_reminder_success(async_client: AsyncClient, test_db: AsyncSession):
    """Create recurring reminder with valid RFC 5545 RRULE."""
    user = await create_test_user(test_db, "recurring@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await async_client.post(
        "/api/v1/reminders",
        json={
            "title": "Daily Standup Reminder",
            "remind_at": trigger_dt,
            "timezone": "Asia/Kolkata",
            "recurrence_rule": "FREQ=DAILY;INTERVAL=1",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["recurrence_rule"] == "FREQ=DAILY;INTERVAL=1"
    assert data["status"] == "scheduled"


@pytest.mark.asyncio
async def test_create_reminder_with_associated_task(async_client: AsyncClient, test_db: AsyncSession):
    """Create reminder linked to an existing task owned by user."""
    user = await create_test_user(test_db, "task_link_user@example.com")
    set_auth_cookie(async_client, user)

    task_resp = await async_client.post("/api/v1/tasks", json={"title": "Linked Task"})
    task_id = task_resp.json()["id"]

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    rem_resp = await async_client.post(
        "/api/v1/reminders",
        json={
            "title": "Task Reminder",
            "remind_at": trigger_dt,
            "task_id": task_id,
        },
    )
    assert rem_resp.status_code == 201
    assert rem_resp.json()["task_id"] == task_id


@pytest.mark.asyncio
async def test_create_reminder_with_unowned_task_rejected(async_client: AsyncClient, test_db: AsyncSession):
    """User A cannot link User B's task to a reminder."""
    user_a = await create_test_user(test_db, "alice_link@example.com")
    user_b = await create_test_user(test_db, "bob_link@example.com")

    # Bob creates a task
    set_auth_cookie(async_client, user_b)
    bob_task = await async_client.post("/api/v1/tasks", json={"title": "Bob Secret Task"})
    bob_task_id = bob_task.json()["id"]

    # Alice attempts to create reminder linking Bob's task
    set_auth_cookie(async_client, user_a)
    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    rem_resp = await async_client.post(
        "/api/v1/reminders",
        json={
            "title": "Alice illegal reminder",
            "remind_at": trigger_dt,
            "task_id": bob_task_id,
        },
    )
    assert rem_resp.status_code == 400
    assert "not found or does not belong to user" in rem_resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_reminder_rejects_naive_datetime(async_client: AsyncClient, test_db: AsyncSession):
    """Naive datetime strings without timezone offset are rejected."""
    user = await create_test_user(test_db, "naive_rem@example.com")
    set_auth_cookie(async_client, user)

    resp = await async_client.post(
        "/api/v1/reminders",
        json={
            "title": "Naive Reminder",
            "remind_at": "2026-09-20T14:30:00",  # No tzinfo
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_reminder_rejects_invalid_rrule(async_client: AsyncClient, test_db: AsyncSession):
    """Invalid RRULE syntax is rejected with 422."""
    user = await create_test_user(test_db, "bad_rrule@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = await async_client.post(
        "/api/v1/reminders",
        json={
            "title": "Bad RRULE Reminder",
            "remind_at": trigger_dt,
            "recurrence_rule": "NOT_A_VALID_RRULE_FORMAT",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_reminders_multi_user_isolation(async_client: AsyncClient, test_db: AsyncSession):
    """User isolation: User A cannot see User B's reminders."""
    user_a = await create_test_user(test_db, "rem_user_a@example.com")
    user_b = await create_test_user(test_db, "rem_user_b@example.com")

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    # User A creates 2 reminders
    set_auth_cookie(async_client, user_a)
    await async_client.post("/api/v1/reminders", json={"title": "User A Rem 1", "remind_at": trigger_dt})
    await async_client.post("/api/v1/reminders", json={"title": "User A Rem 2", "remind_at": trigger_dt})

    # User B creates 1 reminder
    set_auth_cookie(async_client, user_b)
    await async_client.post("/api/v1/reminders", json={"title": "User B Rem", "remind_at": trigger_dt})

    # User B lists reminders
    resp_b = await async_client.get("/api/v1/reminders")
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 1
    assert resp_b.json()["items"][0]["title"] == "User B Rem"

    # User A lists reminders
    set_auth_cookie(async_client, user_a)
    resp_a = await async_client.get("/api/v1/reminders")
    assert resp_a.status_code == 200
    assert resp_a.json()["total"] == 2


@pytest.mark.asyncio
async def test_snooze_reminder_preset_durations(async_client: AsyncClient, test_db: AsyncSession):
    """Snoozing a reminder advances next_trigger_at and sets status to snoozed."""
    user = await create_test_user(test_db, "snoozer@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    create_resp = await async_client.post(
        "/api/v1/reminders",
        json={"title": "Meeting in 10m", "remind_at": trigger_dt},
    )
    rem_id = create_resp.json()["id"]

    # Snooze 15 minutes
    snooze_resp = await async_client.post(
        f"/api/v1/reminders/{rem_id}/snooze",
        json={"duration": "15m"},
    )
    assert snooze_resp.status_code == 200
    data = snooze_resp.json()
    assert data["status"] == "snoozed"
    assert data["snoozed_until"] is not None
    assert data["next_trigger_at"] == data["snoozed_until"]


@pytest.mark.asyncio
async def test_cancel_reminder_lifecycle(async_client: AsyncClient, test_db: AsyncSession):
    """Cancelling a reminder sets status to cancelled and clears next_trigger_at."""
    user = await create_test_user(test_db, "canceller@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    create_resp = await async_client.post(
        "/api/v1/reminders",
        json={"title": "To be cancelled", "remind_at": trigger_dt},
    )
    rem_id = create_resp.json()["id"]

    cancel_resp = await async_client.post(f"/api/v1/reminders/{rem_id}/cancel")
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert data["status"] == "cancelled"
    assert data["next_trigger_at"] is None

    # Snoozing a cancelled reminder must fail
    snooze_resp = await async_client.post(
        f"/api/v1/reminders/{rem_id}/snooze",
        json={"duration": "15m"},
    )
    assert snooze_resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_reminder_success(async_client: AsyncClient, test_db: AsyncSession):
    """Delete a reminder removes it from DB."""
    user = await create_test_user(test_db, "rem_del@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    create_resp = await async_client.post(
        "/api/v1/reminders",
        json={"title": "Delete me", "remind_at": trigger_dt},
    )
    rem_id = create_resp.json()["id"]

    assert (await async_client.delete(f"/api/v1/reminders/{rem_id}")).status_code == 204
    assert (await async_client.get(f"/api/v1/reminders/{rem_id}")).status_code == 404


@pytest.mark.asyncio
async def test_cross_user_reminder_modification_forbidden(async_client: AsyncClient, test_db: AsyncSession):
    """User A cannot snooze, cancel, or delete User B's reminder."""
    user_a = await create_test_user(test_db, "alice_sec@example.com")
    user_b = await create_test_user(test_db, "bob_sec@example.com")

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    set_auth_cookie(async_client, user_a)
    create_resp = await async_client.post(
        "/api/v1/reminders",
        json={"title": "Alice Private Reminder", "remind_at": trigger_dt},
    )
    rem_id = create_resp.json()["id"]

    # Bob attempts operations on Alice's reminder
    set_auth_cookie(async_client, user_b)
    assert (await async_client.get(f"/api/v1/reminders/{rem_id}")).status_code == 404
    assert (await async_client.patch(f"/api/v1/reminders/{rem_id}", json={"title": "Hacked"})).status_code == 404
    assert (await async_client.post(f"/api/v1/reminders/{rem_id}/snooze", json={"duration": "15m"})).status_code == 404
    assert (await async_client.post(f"/api/v1/reminders/{rem_id}/cancel")).status_code == 404
    assert (await async_client.delete(f"/api/v1/reminders/{rem_id}")).status_code == 404


def test_dst_transition_recurrence_calculation_america_new_york():
    """
    Verify DST transition safety for America/New_York (Spring forward & Fall back).
    Ensures wall-clock 09:00 AM remains 09:00 AM local time across DST transitions.
    """
    tz_ny = zoneinfo.ZoneInfo("America/New_York")

    # Day before Spring DST jump (March 7, 2026 at 09:00 EST -> UTC-5)
    base_dt = datetime(2026, 3, 7, 9, 0, 0, tzinfo=tz_ny)
    # Reference time after the first occurrence
    after_dt = datetime(2026, 3, 7, 9, 1, 0, tzinfo=tz_ny)

    # Next daily occurrence should be March 8, 2026 at 09:00 EDT (UTC-4)
    next_dt_utc = compute_next_occurrence(
        recurrence_rule="FREQ=DAILY",
        base_dt=base_dt,
        after_dt=after_dt,
        tz_name="America/New_York",
    )
    assert next_dt_utc is not None
    next_dt_ny = next_dt_utc.astimezone(tz_ny)
    assert next_dt_ny.year == 2026
    assert next_dt_ny.month == 3
    assert next_dt_ny.day == 8
    assert next_dt_ny.hour == 9
    assert next_dt_ny.minute == 0


def test_dst_transition_recurrence_calculation_asia_kolkata():
    """Verify standard recurrence calculation in non-DST timezone Asia/Kolkata."""
    tz_kolkata = zoneinfo.ZoneInfo("Asia/Kolkata")
    base_dt = datetime(2026, 9, 15, 14, 30, 0, tzinfo=tz_kolkata)
    after_dt = datetime(2026, 9, 15, 14, 31, 0, tzinfo=tz_kolkata)

    next_dt_utc = compute_next_occurrence(
        recurrence_rule="FREQ=DAILY",
        base_dt=base_dt,
        after_dt=after_dt,
        tz_name="Asia/Kolkata",
    )
    assert next_dt_utc is not None
    next_dt_local = next_dt_utc.astimezone(tz_kolkata)
    assert next_dt_local.day == 16
    assert next_dt_local.hour == 14
    assert next_dt_local.minute == 30


def test_parse_snooze_duration_helper():
    """Verify snooze duration parser."""
    now = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)
    assert parse_snooze_duration("5m", now) == datetime(2026, 9, 15, 10, 5, 0, tzinfo=timezone.utc)
    assert parse_snooze_duration("15m", now) == datetime(2026, 9, 15, 10, 15, 0, tzinfo=timezone.utc)
    assert parse_snooze_duration("30m", now) == datetime(2026, 9, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert parse_snooze_duration("1h", now) == datetime(2026, 9, 15, 11, 0, 0, tzinfo=timezone.utc)
    assert parse_snooze_duration("1d", now) == datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        parse_snooze_duration("2w", now)


def test_dst_fall_back_transition_recurrence_america_new_york():
    """
    Verify DST fall-back transition for America/New_York (Nov 1, 2026).
    Ensures 09:00 EDT transitions smoothly to 09:00 EST.
    """
    tz_ny = zoneinfo.ZoneInfo("America/New_York")
    base_dt = datetime(2026, 10, 31, 9, 0, 0, tzinfo=tz_ny)
    after_dt = datetime(2026, 10, 31, 9, 1, 0, tzinfo=tz_ny)

    next_dt_utc = compute_next_occurrence(
        recurrence_rule="FREQ=DAILY",
        base_dt=base_dt,
        after_dt=after_dt,
        tz_name="America/New_York",
    )
    assert next_dt_utc is not None
    next_dt_ny = next_dt_utc.astimezone(tz_ny)
    assert next_dt_ny.year == 2026
    assert next_dt_ny.month == 11
    assert next_dt_ny.day == 1
    assert next_dt_ny.hour == 9
    assert next_dt_ny.minute == 0


def test_compute_next_occurrence_with_weekly_recurrence():
    """Test weekly recurrence calculates the correct day 7 days later."""
    base_dt = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)
    after_dt = datetime(2026, 9, 15, 10, 5, 0, tzinfo=timezone.utc)

    next_dt = compute_next_occurrence(
        recurrence_rule="FREQ=WEEKLY;INTERVAL=1",
        base_dt=base_dt,
        after_dt=after_dt,
        tz_name="UTC",
    )
    assert next_dt == datetime(2026, 9, 22, 10, 0, 0, tzinfo=timezone.utc)


def test_compute_next_occurrence_with_monthly_recurrence():
    """Test monthly recurrence calculates the same day next month."""
    base_dt = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)
    after_dt = datetime(2026, 9, 15, 10, 5, 0, tzinfo=timezone.utc)

    next_dt = compute_next_occurrence(
        recurrence_rule="FREQ=MONTHLY;INTERVAL=1",
        base_dt=base_dt,
        after_dt=after_dt,
        tz_name="UTC",
    )
    assert next_dt == datetime(2026, 10, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_snooze_reminder_custom_snooze_until_in_future(async_client: AsyncClient, test_db: AsyncSession):
    """Snooze reminder with explicit snooze_until datetime."""
    user = await create_test_user(test_db, "custom_snooze@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    create_resp = await async_client.post(
        "/api/v1/reminders",
        json={"title": "Custom snooze target", "remind_at": trigger_dt},
    )
    rem_id = create_resp.json()["id"]

    custom_dt = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    snooze_resp = await async_client.post(
        f"/api/v1/reminders/{rem_id}/snooze",
        json={"snooze_until": custom_dt},
    )
    assert snooze_resp.status_code == 200
    assert snooze_resp.json()["status"] == "snoozed"
    assert snooze_resp.json()["snoozed_until"] is not None


@pytest.mark.asyncio
async def test_snooze_reminder_past_datetime_rejected(async_client: AsyncClient, test_db: AsyncSession):
    """Snoozing to a time in the past is rejected with 400."""
    user = await create_test_user(test_db, "past_snooze@example.com")
    set_auth_cookie(async_client, user)

    trigger_dt = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    create_resp = await async_client.post(
        "/api/v1/reminders",
        json={"title": "Past snooze test", "remind_at": trigger_dt},
    )
    rem_id = create_resp.json()["id"]

    past_custom_dt = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    snooze_resp = await async_client.post(
        f"/api/v1/reminders/{rem_id}/snooze",
        json={"snooze_until": past_custom_dt},
    )
    assert snooze_resp.status_code == 400
    assert "must be in the future" in snooze_resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_reminders_filter_by_task_id(async_client: AsyncClient, test_db: AsyncSession):
    """Filter reminders by associated task_id."""
    user = await create_test_user(test_db, "task_filter_user@example.com")
    set_auth_cookie(async_client, user)

    task_resp = await async_client.post("/api/v1/tasks", json={"title": "Specific Task"})
    task_id = task_resp.json()["id"]

    trigger_dt = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await async_client.post("/api/v1/reminders", json={"title": "Linked Rem", "remind_at": trigger_dt, "task_id": task_id})
    await async_client.post("/api/v1/reminders", json={"title": "Unlinked Rem", "remind_at": trigger_dt})

    resp = await async_client.get(f"/api/v1/reminders?task_id={task_id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["title"] == "Linked Rem"

