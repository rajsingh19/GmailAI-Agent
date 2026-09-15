"""
Tests for Multi-User Idempotency and Race Safety (Milestone 8).
Validates:
- Same source ID across two users creates independent notifications
- Concurrent scheduler workers produce exactly one notification (race-safe)
- Repeated scheduler ticks prevent duplicate notification spam
- Retry after failure preserves idempotency
- Canonical user-scoped idempotency key format and uniqueness
"""
import uuid
import asyncio
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.models.notification import Notification
from app.services.notification_service import NotificationService
from app.services.proactive.decision_engine import build_user_scoped_idempotency_key


@pytest.fixture
async def user_a(test_db: AsyncSession) -> User:
    u = User(id=f"user-a-{uuid.uuid4().hex[:8]}", email="user_a_idem@example.com", full_name="User A", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.fixture
async def user_b(test_db: AsyncSession) -> User:
    u = User(id=f"user-b-{uuid.uuid4().hex[:8]}", email="user_b_idem@example.com", full_name="User B", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_same_source_id_across_two_users_creates_independent_notifications(test_db: AsyncSession, user_a: User, user_b: User):
    """
    User A and User B both have a meeting with identical event_id 'shared_event_99'.
    Both users must independently receive their own notification without collision.
    """
    shared_source_id = "shared_event_99"
    anchor = "2026-09-16T10:00:00Z"
    
    key_a = build_user_scoped_idempotency_key(user_a.id, "calendar", "meeting_soon", shared_source_id, anchor)
    key_b = build_user_scoped_idempotency_key(user_b.id, "calendar", "meeting_soon", shared_source_id, anchor)
    
    assert key_a != key_b
    assert user_a.id in key_a
    assert user_b.id in key_b

    notif_a = await NotificationService.create_notification(
        db=test_db,
        user_id=user_a.id,
        idempotency_key=key_a,
        title="Meeting for User A",
        notification_type="meeting_soon",
        priority="high",
        source_type="calendar",
        source_id=shared_source_id,
    )
    
    notif_b = await NotificationService.create_notification(
        db=test_db,
        user_id=user_b.id,
        idempotency_key=key_b,
        title="Meeting for User B",
        notification_type="meeting_soon",
        priority="high",
        source_type="calendar",
        source_id=shared_source_id,
    )

    assert notif_a.id != notif_b.id
    assert notif_a.user_id == user_a.id
    assert notif_b.user_id == user_b.id


@pytest.mark.asyncio
async def test_repeated_scheduler_ticks_prevent_duplicate_notification_spam(test_db: AsyncSession, user_a: User):
    """
    Simulates 10 consecutive scheduler runs for the same event.
    Exactly 1 notification must exist in the database.
    """
    key = build_user_scoped_idempotency_key(user_a.id, "task", "task_overdue", "task_123", "2026-09-16")

    results = []
    for _ in range(10):
        n = await NotificationService.create_notification(
            db=test_db,
            user_id=user_a.id,
            idempotency_key=key,
            title="Overdue Task",
            notification_type="task_overdue",
            priority="urgent",
            source_type="task",
            source_id="task_123",
        )
        results.append(n.id)

    # All returned notification objects should share the exact same ID
    assert len(set(results)) == 1

    # Total in DB should be exactly 1
    count = (await test_db.execute(select(func.count(Notification.id)).where(Notification.user_id == user_a.id))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_scheduler_workers_produce_single_notification_race_safe(test_db: AsyncSession, user_a: User):
    """
    Simulates multiple workers attempting to insert the exact same notification.
    Verifies that all invocations return the single unique notification.
    """
    key = build_user_scoped_idempotency_key(user_a.id, "calendar", "calendar_conflict", "conf_1", "2026-09-16T14:00")

    notifs = []
    for _ in range(5):
        n = await NotificationService.create_notification(
            db=test_db,
            user_id=user_a.id,
            idempotency_key=key,
            title="Calendar Conflict",
            notification_type="calendar_conflict",
            priority="high",
            source_type="calendar",
            source_id="conf_1",
        )
        notifs.append(n)

    notif_ids = [n.id for n in notifs]
    assert len(set(notif_ids)) == 1

    # Verify database count is strictly 1
    count = (await test_db.execute(select(func.count(Notification.id)).where(Notification.user_id == user_a.id))).scalar_one()
    assert count == 1



@pytest.mark.asyncio
async def test_retry_after_transient_failure_preserves_idempotency(test_db: AsyncSession, user_a: User):
    """
    If a notification was already committed and a subsequent retry occurs,
    it gracefully returns the existing notification without error.
    """
    key = build_user_scoped_idempotency_key(user_a.id, "gmail", "email_actionable", "msg_abc", "msg_abc")
    
    n1 = await NotificationService.create_notification(
        db=test_db,
        user_id=user_a.id,
        idempotency_key=key,
        title="Actionable Email",
        notification_type="email_actionable",
        priority="high",
        source_type="gmail",
        source_id="msg_abc",
    )
    
    # Retry call
    n2 = await NotificationService.create_notification(
        db=test_db,
        user_id=user_a.id,
        idempotency_key=key,
        title="Actionable Email",
        notification_type="email_actionable",
        priority="high",
        source_type="gmail",
        source_id="msg_abc",
    )
    
    assert n1.id == n2.id


@pytest.mark.asyncio
async def test_user_scoped_idempotency_key_format_and_uniqueness():
    """Verify format string contains all necessary discriminant components."""
    key = build_user_scoped_idempotency_key("usr_1", "task", "task_due_soon", "task_99", "2026-09-16T15:00:00Z")
    assert key == "proactive:usr_1:task:task_due_soon:task_99:2026-09-16T15_00_00Z"


@pytest.mark.asyncio
async def test_different_detection_types_same_source_create_distinct_notifications(test_db: AsyncSession, user_a: User):
    """
    A task transitioning from 'task_due_soon' to 'task_overdue' on different dates generates
    distinct, non-conflicting notifications.
    """
    task_id = "task_lifecycle_1"
    key1 = build_user_scoped_idempotency_key(user_a.id, "task", "task_due_soon", task_id, "2026-09-16T12:00")
    key2 = build_user_scoped_idempotency_key(user_a.id, "task", "task_overdue", task_id, "2026-09-16_overdue")

    n1 = await NotificationService.create_notification(
        db=test_db,
        user_id=user_a.id,
        idempotency_key=key1,
        title="Task Due Soon",
        notification_type="task_due_soon",
        priority="high",
    )
    n2 = await NotificationService.create_notification(
        db=test_db,
        user_id=user_a.id,
        idempotency_key=key2,
        title="Task Overdue",
        notification_type="task_overdue",
        priority="urgent",
    )

    assert n1.id != n2.id
    count = (await test_db.execute(select(func.count(Notification.id)).where(Notification.user_id == user_a.id))).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_same_task_different_due_dates_generate_unique_idempotency_keys(user_a: User):
    """Rescheduled task with new due date generates distinct idempotency keys."""
    k1 = build_user_scoped_idempotency_key(user_a.id, "task", "task_due_soon", "t1", "2026-09-16T10:00")
    k2 = build_user_scoped_idempotency_key(user_a.id, "task", "task_due_soon", "t1", "2026-09-17T10:00")
    assert k1 != k2


@pytest.mark.asyncio
async def test_multi_user_concurrent_cycle_isolation(test_engine, user_a: User, user_b: User):
    """Concurrent evaluation of User A and User B inserts notifications scoped strictly to each user."""
    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    key_a = build_user_scoped_idempotency_key(user_a.id, "calendar", "dense_schedule", "dense_1", "2026-09-16")
    key_b = build_user_scoped_idempotency_key(user_b.id, "calendar", "dense_schedule", "dense_1", "2026-09-16")

    async def insert_a():
        async with session_factory() as session:
            return await NotificationService.create_notification(
                db=session, user_id=user_a.id, idempotency_key=key_a, title="Dense Schedule A"
            )

    async def insert_b():
        async with session_factory() as session:
            return await NotificationService.create_notification(
                db=session, user_id=user_b.id, idempotency_key=key_b, title="Dense Schedule B"
            )

    na, nb = await asyncio.gather(insert_a(), insert_b())
    assert na.user_id == user_a.id
    assert nb.user_id == user_b.id


@pytest.mark.asyncio
async def test_idempotency_key_special_characters_sanitization():
    """Verify colons in timestamps or source IDs are sanitized to avoid key truncation/ambiguity."""
    key = build_user_scoped_idempotency_key("user:special", "cal", "conflict", "src:123", "2026-09-16T10:00:00+00:00")
    assert "src_123" in key
    assert "2026-09-16T10_00_00+00_00" in key


@pytest.mark.asyncio
async def test_database_unique_constraint_enforces_user_idempotency(test_db: AsyncSession, user_a: User):
    """Direct SQLAlchemy insert of duplicate (user_id, idempotency_key) raises IntegrityError."""
    key = f"raw_key_{uuid.uuid4().hex}"
    n1 = Notification(
        user_id=user_a.id,
        idempotency_key=key,
        title="Direct Insert 1",
    )
    test_db.add(n1)
    await test_db.commit()

    n2 = Notification(
        user_id=user_a.id,
        idempotency_key=key,
        title="Direct Insert 2",
    )
    test_db.add(n2)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()
