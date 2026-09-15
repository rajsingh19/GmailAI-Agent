"""
Test Suite for Scheduler, Atomic Claiming, Idempotency, and In-App Notifications (Milestone 5).
Validates:
- One-time reminder trigger lifecycle (scheduled -> processing -> triggered)
- Recurring reminder trigger lifecycle (scheduled -> processing -> scheduled + next_occurrence)
- Atomic claiming safety & concurrent claiming race condition
- Notification creation & idempotency key deduplication
- Bounded retry semantics (max 3 attempts -> failed)
- Overdue recovery policy (handles offline missed triggers cleanly)
- Scheduler startup, shutdown, and duplicate scheduler prevention
- In-app notification API endpoints & multi-user isolation
"""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.models.reminder import Reminder
from app.models.notification import Notification
from app.services.scheduler_service import SchedulerService
from app.services.notification_service import NotificationService


async def create_test_user(test_db: AsyncSession, email: str = "sched_user@example.com") -> User:
    user = User(email=email, full_name="Scheduler Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.fixture(autouse=True)
def cleanup_scheduler_singleton():
    """Ensure scheduler singleton is reset before and after each test."""
    SchedulerService.reset_instance_for_testing()
    yield
    SchedulerService.reset_instance_for_testing()


# =============================================================================
# 1. Scheduler Lifecycle & Duplicate Prevention Tests
# =============================================================================

@pytest.mark.asyncio
async def test_scheduler_singleton_and_duplicate_startup_prevention():
    """Starting the scheduler multiple times does not register duplicate jobs."""
    scheduler_service = SchedulerService.get_instance()
    scheduler_service.start()
    assert scheduler_service.is_running

    # Second start call should be a no-op
    scheduler_service.start()
    assert scheduler_service.is_running

    # Verify registered jobs
    jobs = scheduler_service._scheduler.get_jobs()
    job_ids = [j.id for j in jobs]
    assert "poll_due_reminders_job" in job_ids
    assert "proactive_monitor_job" in job_ids
    assert len(jobs) == 2

    # Shutdown
    scheduler_service.shutdown()
    assert not scheduler_service.is_running


# =============================================================================
# 2. One-Time & Recurring Reminder Execution Lifecycle
# =============================================================================

@pytest.mark.asyncio
async def test_one_time_reminder_execution(test_db: AsyncSession, test_engine):
    """Due one-time reminder transitions to triggered and creates in-app notification."""
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    user = await create_test_user(test_db, "onetime_exec@example.com")

    # Seed due reminder in past
    past_dt = datetime.now(timezone.utc) - timedelta(minutes=5)
    reminder = Reminder(
        user_id=user.id,
        title="Check Server Logs",
        message="Review 500 errors",
        remind_at=past_dt,
        timezone="UTC",
        status="scheduled",
        next_trigger_at=past_dt,
    )
    test_db.add(reminder)
    await test_db.commit()
    await test_db.refresh(reminder)

    scheduler = SchedulerService.get_instance()

    with patch("app.services.scheduler_service.AsyncSessionLocal", session_factory):
        processed = await scheduler.process_due_reminders()

    assert processed == 1

    # Verify reminder state is triggered and next_trigger_at is None
    await test_db.refresh(reminder)
    assert reminder.status == "triggered"
    assert reminder.next_trigger_at is None
    assert reminder.last_triggered_at is not None

    # Verify notification created
    notif_stmt = select(Notification).where(Notification.reminder_id == reminder.id)
    notif_res = await test_db.execute(notif_stmt)
    notif = notif_res.scalar_one_or_none()
    assert notif is not None
    assert notif.title == "Reminder: Check Server Logs"
    assert notif.status == "unread"
    assert notif.user_id == user.id


@pytest.mark.asyncio
async def test_recurring_reminder_execution(test_db: AsyncSession, test_engine):
    """Due recurring reminder creates notification and updates next_trigger_at safely."""
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    user = await create_test_user(test_db, "recurring_exec@example.com")

    past_dt = datetime.now(timezone.utc) - timedelta(minutes=5)
    reminder = Reminder(
        user_id=user.id,
        title="Daily Standup",
        message="Join Meet link",
        remind_at=past_dt,
        timezone="UTC",
        recurrence_rule="FREQ=DAILY",
        status="scheduled",
        next_trigger_at=past_dt,
    )
    test_db.add(reminder)
    await test_db.commit()
    await test_db.refresh(reminder)

    scheduler = SchedulerService.get_instance()

    with patch("app.services.scheduler_service.AsyncSessionLocal", session_factory):
        processed = await scheduler.process_due_reminders()

    assert processed == 1

    # Verify reminder is back in scheduled state with next occurrence
    await test_db.refresh(reminder)
    assert reminder.status == "scheduled"
    assert reminder.next_trigger_at is not None
    next_trigger = (
        reminder.next_trigger_at.replace(tzinfo=timezone.utc)
        if reminder.next_trigger_at.tzinfo is None
        else reminder.next_trigger_at
    )
    assert next_trigger > datetime.now(timezone.utc)
    assert reminder.last_triggered_at is not None


# =============================================================================
# 3. Atomic Claiming & Concurrency Safety
# =============================================================================

@pytest.mark.asyncio
async def test_atomic_claim_concurrency_race(test_db: AsyncSession, test_engine):
    """Simulate 2 workers claiming the same reminder; exactly one succeeds."""
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    user = await create_test_user(test_db, "race_user@example.com")

    past_dt = datetime.now(timezone.utc) - timedelta(minutes=1)
    reminder = Reminder(
        user_id=user.id,
        title="Concurrent Claim Target",
        remind_at=past_dt,
        status="scheduled",
        next_trigger_at=past_dt,
    )
    test_db.add(reminder)
    await test_db.commit()
    await test_db.refresh(reminder)

    scheduler = SchedulerService.get_instance()

    with patch("app.services.scheduler_service.AsyncSessionLocal", session_factory):
        # Run two claim attempts concurrently
        res1, res2 = await asyncio.gather(
            scheduler._claim_and_execute_reminder(reminder.id),
            scheduler._claim_and_execute_reminder(reminder.id),
        )

    # Exactly one worker must succeed
    assert (res1 is True and res2 is False) or (res1 is False and res2 is True)

    # Verify exactly one notification in database
    notif_stmt = select(Notification).where(Notification.reminder_id == reminder.id)
    notif_res = await test_db.execute(notif_stmt)
    notifications = list(notif_res.scalars().all())
    assert len(notifications) == 1


# =============================================================================
# 4. Idempotency & Duplicate Notification Prevention
# =============================================================================

@pytest.mark.asyncio
async def test_notification_creation_idempotency(test_db: AsyncSession):
    """Multiple calls with identical idempotency key return existing record without creating duplicate."""
    user = await create_test_user(test_db, "idempotent@example.com")
    key = "rem-123:2026-09-15T10:00:00+00:00"

    n1 = await NotificationService.create_notification(
        db=test_db,
        user_id=user.id,
        idempotency_key=key,
        title="Reminder Title",
        message="Message",
    )
    assert n1 is not None

    n2 = await NotificationService.create_notification(
        db=test_db,
        user_id=user.id,
        idempotency_key=key,
        title="Reminder Title",
        message="Message",
    )
    assert n2.id == n1.id

    # Verify total in DB is 1
    res = await test_db.execute(select(Notification).where(Notification.user_id == user.id))
    assert len(list(res.scalars().all())) == 1


# =============================================================================
# 5. Overdue Recovery Policy
# =============================================================================

@pytest.mark.asyncio
async def test_overdue_recurring_reminder_recovery_creates_single_notification(test_db: AsyncSession, test_engine):
    """
    If application was offline and multiple recurrence cycles were missed,
    scheduler creates at most ONE recovery notification and fast-forwards next_trigger_at to future.
    """
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    user = await create_test_user(test_db, "overdue_recovery@example.com")

    # Scheduled 3 days ago, daily recurrence (3 missed days)
    old_dt = datetime.now(timezone.utc) - timedelta(days=3)
    reminder = Reminder(
        user_id=user.id,
        title="Daily Standup Missed",
        remind_at=old_dt,
        timezone="UTC",
        recurrence_rule="FREQ=DAILY",
        status="scheduled",
        next_trigger_at=old_dt,
    )
    test_db.add(reminder)
    await test_db.commit()
    await test_db.refresh(reminder)

    scheduler = SchedulerService.get_instance()

    with patch("app.services.scheduler_service.AsyncSessionLocal", session_factory):
        processed = await scheduler.process_due_reminders()

    assert processed == 1

    # Exactly 1 notification created
    notifs = (await test_db.execute(select(Notification).where(Notification.reminder_id == reminder.id))).scalars().all()
    assert len(list(notifs)) == 1

    # Next trigger is safely in the future
    await test_db.refresh(reminder)
    assert reminder.status == "scheduled"
    next_trigger = (
        reminder.next_trigger_at.replace(tzinfo=timezone.utc)
        if reminder.next_trigger_at.tzinfo is None
        else reminder.next_trigger_at
    )
    assert next_trigger > datetime.now(timezone.utc)


# =============================================================================
# 6. Retry & Failure Semantics
# =============================================================================

@pytest.mark.asyncio
async def test_reminder_execution_failure_bounded_retries(test_db: AsyncSession, test_engine):
    """Execution failures retry with backoff, marking reminder as failed after 3 attempts."""
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    user = await create_test_user(test_db, "retry_user@example.com")

    past_dt = datetime.now(timezone.utc) - timedelta(minutes=1)
    reminder = Reminder(
        user_id=user.id,
        title="Failing Reminder",
        remind_at=past_dt,
        status="scheduled",
        next_trigger_at=past_dt,
        retry_count=2,  # 2nd failure already occurred
    )
    test_db.add(reminder)
    await test_db.commit()
    await test_db.refresh(reminder)

    scheduler = SchedulerService.get_instance()

    # Force NotificationService to raise an error
    with patch("app.services.scheduler_service.AsyncSessionLocal", session_factory), \
         patch.object(NotificationService, "create_notification", side_effect=RuntimeError("Simulated Delivery Failure")):
        success = await scheduler._claim_and_execute_reminder(reminder.id)

    assert success is False

    # 3rd attempt reached -> status is failed
    await test_db.refresh(reminder)
    assert reminder.status == "failed"
    assert reminder.retry_count == 3
    assert reminder.next_trigger_at is None


# =============================================================================
# 7. In-App Notification Endpoints & Multi-User Isolation
# =============================================================================

@pytest.mark.asyncio
async def test_notification_endpoints_and_user_isolation(async_client: AsyncClient, test_db: AsyncSession):
    """Notification listing, marking read, and isolation across users."""
    user_a = await create_test_user(test_db, "notif_a@example.com")
    user_b = await create_test_user(test_db, "notif_b@example.com")

    # Seed notification for user A
    await NotificationService.create_notification(
        db=test_db,
        user_id=user_a.id,
        idempotency_key="key_a_1",
        title="User A Alert",
        message="Important note",
    )
    # Seed notification for user B
    await NotificationService.create_notification(
        db=test_db,
        user_id=user_b.id,
        idempotency_key="key_b_1",
        title="User B Alert",
    )

    # User A requests notifications
    set_auth_cookie(async_client, user_a)
    resp_a = await async_client.get("/api/v1/notifications")
    assert resp_a.status_code == 200
    assert resp_a.json()["total"] == 1
    assert resp_a.json()["unread_count"] == 1
    assert resp_a.json()["items"][0]["title"] == "User A Alert"

    # User A marks notification as read
    notif_id = resp_a.json()["items"][0]["id"]
    read_resp = await async_client.post("/api/v1/notifications/read", json={"notification_ids": [notif_id]})
    assert read_resp.status_code == 200
    assert read_resp.json()["marked_read_count"] == 1

    # Verify unread_count is now 0 for User A
    resp_a2 = await async_client.get("/api/v1/notifications")
    assert resp_a2.json()["unread_count"] == 0

    # User B notifications remain unread
    set_auth_cookie(async_client, user_b)
    resp_b = await async_client.get("/api/v1/notifications")
    assert resp_b.status_code == 200
    assert resp_b.json()["unread_count"] == 1


@pytest.mark.asyncio
async def test_mark_all_notifications_as_read_endpoint(async_client: AsyncClient, test_db: AsyncSession):
    """Mark all unread notifications as read when notification_ids is omitted."""
    user = await create_test_user(test_db, "read_all_user@example.com")
    set_auth_cookie(async_client, user)

    await NotificationService.create_notification(
        db=test_db, user_id=user.id, idempotency_key="k1", title="Notif 1"
    )
    await NotificationService.create_notification(
        db=test_db, user_id=user.id, idempotency_key="k2", title="Notif 2"
    )

    read_all_resp = await async_client.post("/api/v1/notifications/read", json={})
    assert read_all_resp.status_code == 200
    assert read_all_resp.json()["marked_read_count"] == 2

    get_resp = await async_client.get("/api/v1/notifications")
    assert get_resp.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_delete_notification_endpoint_and_isolation(async_client: AsyncClient, test_db: AsyncSession):
    """Delete a notification and verify cross-user deletion is forbidden."""
    user_a = await create_test_user(test_db, "notif_del_a@example.com")
    user_b = await create_test_user(test_db, "notif_del_b@example.com")

    notif = await NotificationService.create_notification(
        db=test_db, user_id=user_a.id, idempotency_key="del_k", title="To Delete"
    )

    # Bob cannot delete Alice's notification
    set_auth_cookie(async_client, user_b)
    assert (await async_client.delete(f"/api/v1/notifications/{notif.id}")).status_code == 404

    # Alice deletes her notification
    set_auth_cookie(async_client, user_a)
    assert (await async_client.delete(f"/api/v1/notifications/{notif.id}")).status_code == 204


@pytest.mark.asyncio
async def test_scheduler_process_due_reminders_empty_db_returns_zero(test_engine):
    """When no reminders are due, process_due_reminders returns 0."""
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    scheduler = SchedulerService.get_instance()

    with patch("app.services.scheduler_service.AsyncSessionLocal", session_factory):
        count = await scheduler.process_due_reminders()

    assert count == 0


@pytest.mark.asyncio
async def test_cancelled_reminder_never_executed_by_scheduler(test_db: AsyncSession, test_engine):
    """A reminder cancelled before execution must never trigger or create notifications."""
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    user = await create_test_user(test_db, "cancelled_sched@example.com")

    past_dt = datetime.now(timezone.utc) - timedelta(minutes=5)
    reminder = Reminder(
        user_id=user.id,
        title="Cancelled Before Due",
        remind_at=past_dt,
        status="cancelled",
        next_trigger_at=None,
    )
    test_db.add(reminder)
    await test_db.commit()

    scheduler = SchedulerService.get_instance()
    with patch("app.services.scheduler_service.AsyncSessionLocal", session_factory):
        processed = await scheduler.process_due_reminders()

    assert processed == 0
    notifs = (await test_db.execute(select(Notification).where(Notification.user_id == user.id))).scalars().all()
    assert len(list(notifs)) == 0

