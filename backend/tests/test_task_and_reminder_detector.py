"""
Tests for Task and Reminder Detectors (Milestone 8).
Validates:
- Task overdue detection and complete_task suggested action
- Task due soon (<= 4h) high-priority detection
- Stale urgent task detection (>7d without update)
- Completed / cancelled tasks excluded from detection
- Repeatedly snoozed reminder (>= 3 times) detection
- Missed recurring reminder detection
- Multi-user data isolation
"""
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.task import Task
from app.models.reminder import Reminder
from app.services.proactive.detectors.task_detector import TaskDetector
from app.services.proactive.detectors.reminder_detector import ReminderDetector
from app.ai.agent.tool_registry import RiskLevel


@pytest.fixture
async def user_t(test_db: AsyncSession) -> User:
    u = User(id=f"user-t-{uuid.uuid4().hex[:8]}", email="task_det_tester@example.com", full_name="Task Tester", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.fixture
async def other_user_t(test_db: AsyncSession) -> User:
    u = User(id=f"user-other-t-{uuid.uuid4().hex[:8]}", email="other_task_tester@example.com", full_name="Other Task Tester", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_task_overdue_detection_and_suggested_action(test_db: AsyncSession, user_t: User):
    """Overdue task generates 'task_overdue' alert with complete_task suggested action."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    task = Task(
        user_id=user_t.id,
        title="Submit Q3 Tax Filing",
        status="pending",
        priority="urgent",
        due_at=now - timedelta(days=2),
    )
    test_db.add(task)
    await test_db.commit()

    detector = TaskDetector()
    candidates = await detector.detect_tasks(test_db, user_t.id, now_utc=now)

    assert len(candidates) >= 1
    overdue = next(c for c in candidates if c["detection_type"] == "task_overdue")
    assert overdue["source_id"] == task.id
    assert overdue["priority"] == "urgent"
    assert "2 days ago" in overdue["message"]

    action = overdue["suggested_action"]
    assert action.action_type == "complete_task"
    assert action.risk_level == RiskLevel.LOW_RISK_WRITE
    assert action.action_payload["task_id"] == task.id


@pytest.mark.asyncio
async def test_task_due_soon_high_priority_detection(test_db: AsyncSession, user_t: User):
    """Task due in 2 hours with priority='high' generates 'task_due_soon' alert."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    task = Task(
        user_id=user_t.id,
        title="Prepare Board Meeting Slides",
        status="pending",
        priority="high",
        due_at=now + timedelta(hours=2),
    )
    test_db.add(task)
    await test_db.commit()

    detector = TaskDetector()
    candidates = await detector.detect_tasks(test_db, user_t.id, now_utc=now)

    due_soon = next((c for c in candidates if c["detection_type"] == "task_due_soon"), None)
    assert due_soon is not None
    assert due_soon["source_id"] == task.id
    assert due_soon["priority"] == "high"
    assert "2h 0m" in due_soon["title"] or "2 hours" in due_soon["title"]


@pytest.mark.asyncio
async def test_task_due_soon_low_priority_not_flagged(test_db: AsyncSession, user_t: User):
    """Task due in 2 hours with priority='low' is not flagged as due_soon."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    task = Task(
        user_id=user_t.id,
        title="Water Office Plants",
        status="pending",
        priority="low",
        due_at=now + timedelta(hours=2),
    )
    test_db.add(task)
    await test_db.commit()

    detector = TaskDetector()
    candidates = await detector.detect_tasks(test_db, user_t.id, now_utc=now)
    due_soon = [c for c in candidates if c["detection_type"] == "task_due_soon" and c["source_id"] == task.id]
    assert len(due_soon) == 0


@pytest.mark.asyncio
async def test_stale_urgent_task_detection(test_db: AsyncSession, user_t: User):
    """Task with priority='urgent' without due date updated 10 days ago triggers 'stale_urgent_task'."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    task = Task(
        user_id=user_t.id,
        title="Upgrade Core Production Database",
        status="in_progress",
        priority="urgent",
        due_at=None,
        created_at=now - timedelta(days=15),
        updated_at=now - timedelta(days=10),
    )
    test_db.add(task)
    await test_db.commit()

    detector = TaskDetector()
    candidates = await detector.detect_tasks(test_db, user_t.id, now_utc=now)

    stale = next((c for c in candidates if c["detection_type"] == "stale_urgent_task"), None)
    assert stale is not None
    assert stale["source_id"] == task.id
    assert stale["priority"] == "medium"


@pytest.mark.asyncio
async def test_completed_tasks_excluded_from_detection(test_db: AsyncSession, user_t: User):
    """Completed tasks with past due dates are never flagged as overdue."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    task = Task(
        user_id=user_t.id,
        title="Already Done Task",
        status="completed",
        due_at=now - timedelta(days=5),
    )
    test_db.add(task)
    await test_db.commit()

    detector = TaskDetector()
    candidates = await detector.detect_tasks(test_db, user_t.id, now_utc=now)
    assert not any(c["source_id"] == task.id for c in candidates)


@pytest.mark.asyncio
async def test_reminder_repeated_snoozing_detection(test_db: AsyncSession, user_t: User):
    """Reminder with retry_count=4 in snoozed status triggers 'repeated_snoozing' proactive warning."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    reminder = Reminder(
        user_id=user_t.id,
        title="Review Gym Membership Renewal",
        status="snoozed",
        retry_count=4,
        remind_at=now + timedelta(hours=1),
    )
    test_db.add(reminder)
    await test_db.commit()

    detector = ReminderDetector()
    candidates = await detector.detect_reminders(test_db, user_t.id, now_utc=now)

    assert len(candidates) >= 1
    snoozed = next(c for c in candidates if c["detection_type"] == "repeated_snoozing")
    assert snoozed["source_id"] == reminder.id
    assert "4 times" in snoozed["message"]
    assert snoozed["suggested_action"].action_type == "snooze_reminder"


@pytest.mark.asyncio
async def test_reminder_snoozed_less_than_3_times_not_flagged(test_db: AsyncSession, user_t: User):
    """Reminder with retry_count=2 is not flagged for repeated snoozing."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    reminder = Reminder(
        user_id=user_t.id,
        title="Check Mailbox",
        status="snoozed",
        retry_count=2,
        remind_at=now + timedelta(hours=1),
    )
    test_db.add(reminder)
    await test_db.commit()

    detector = ReminderDetector()
    candidates = await detector.detect_reminders(test_db, user_t.id, now_utc=now)
    assert not any(c.get("detection_type") == "repeated_snoozing" and c["source_id"] == reminder.id for c in candidates)


@pytest.mark.asyncio
async def test_missed_recurring_reminder_detection(test_db: AsyncSession, user_t: User):
    """Recurring reminder scheduled for 2 days ago that is still scheduled triggers 'missed_recurring'."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    reminder = Reminder(
        user_id=user_t.id,
        title="Weekly Team Status Update",
        status="scheduled",
        recurrence_rule="FREQ=WEEKLY;INTERVAL=1",
        remind_at=now - timedelta(days=2),
    )
    test_db.add(reminder)
    await test_db.commit()

    detector = ReminderDetector()
    candidates = await detector.detect_reminders(test_db, user_t.id, now_utc=now)

    missed = next((c for c in candidates if c["detection_type"] == "missed_recurring"), None)
    assert missed is not None
    assert missed["source_id"] == reminder.id
    assert missed["priority"] == "high"


@pytest.mark.asyncio
async def test_task_detector_user_isolation(test_db: AsyncSession, user_t: User, other_user_t: User):
    """Tasks belonging to User A are never returned when detector runs for User B."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    task_a = Task(
        user_id=user_t.id,
        title="Confidential Strategy for User A",
        status="pending",
        due_at=now - timedelta(days=1),
    )
    test_db.add(task_a)
    await test_db.commit()

    detector = TaskDetector()
    candidates_b = await detector.detect_tasks(test_db, other_user_t.id, now_utc=now)
    assert not any(c["source_id"] == task_a.id for c in candidates_b)


@pytest.mark.asyncio
async def test_reminder_detector_user_isolation(test_db: AsyncSession, user_t: User, other_user_t: User):
    """Reminders belonging to User A are never returned when detector runs for User B."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    rem_a = Reminder(
        user_id=user_t.id,
        title="User A Private Reminder",
        status="snoozed",
        retry_count=5,
        remind_at=now + timedelta(hours=1),
    )
    test_db.add(rem_a)
    await test_db.commit()

    detector = ReminderDetector()
    candidates_b = await detector.detect_reminders(test_db, other_user_t.id, now_utc=now)
    assert not any(c["source_id"] == rem_a.id for c in candidates_b)
