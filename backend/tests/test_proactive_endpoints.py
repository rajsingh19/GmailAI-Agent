"""
Tests for Proactive REST API Endpoints (/api/v1/proactive/*).
Verifies authentication, user isolation, preferences, notification feed,
actions execution, snooze, dismiss, read, and check triggering.
"""

import pytest
from httpx import AsyncClient
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.models.notification import Notification
from app.models.user_preference import UserPreference
from app.models.task import Task
from app.models.reminder import Reminder


async def create_user(db: AsyncSession, email: str = "proactive_tester@example.com") -> User:
    u = User(email=email, full_name="Proactive Tester", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def authenticate_client(client: AsyncClient, user: User):
    token = SecurityManager.create_session_token(user_id=user.id)
    client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_proactive_endpoints_unauthenticated(async_client: AsyncClient):
    """Unauthenticated requests must be rejected with 401."""
    resp = await async_client.get("/api/v1/proactive/status")
    assert resp.status_code == 401

    resp = await async_client.get("/api/v1/proactive/preferences")
    assert resp.status_code == 401

    resp = await async_client.patch("/api/v1/proactive/preferences", json={"proactive_enabled": True})
    assert resp.status_code == 401

    resp = await async_client.get("/api/v1/proactive/notifications")
    assert resp.status_code == 401

    resp = await async_client.post("/api/v1/proactive/trigger-check")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_proactive_status_and_preferences(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Status returns preference state and pending notification count."""
    user = await create_user(test_db, "pref_user@example.com")
    authenticate_client(async_client, user)

    # Initially proactive is disabled by default
    resp = await async_client.get("/api/v1/proactive/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["proactive_enabled"] is False
    assert data["total_active_alerts"] == 0
    assert "in_quiet_hours" in data

    # Get preferences
    resp = await async_client.get("/api/v1/proactive/preferences")
    assert resp.status_code == 200
    pref_data = resp.json()
    assert pref_data["user_id"] == str(user.id)
    assert pref_data["proactive_enabled"] is False
    assert pref_data["user_timezone"] == "UTC"

    # Update preferences: enable proactive monitoring and quiet hours
    patch_payload = {
        "proactive_enabled": True,
        "calendar_alerts_enabled": True,
        "task_alerts_enabled": True,
        "email_alerts_enabled": False,
        "user_timezone": "America/New_York",
        "quiet_hours_enabled": True,
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "07:00",
        "min_priority": "medium",
        "max_proactive_per_day": 20,
        "cooldown_minutes": 45,
    }
    resp = await async_client.patch("/api/v1/proactive/preferences", json=patch_payload)
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["proactive_enabled"] is True
    assert updated["email_alerts_enabled"] is False
    assert updated["user_timezone"] == "America/New_York"
    assert updated["max_proactive_per_day"] == 20
    assert updated["cooldown_minutes"] == 45


@pytest.mark.asyncio
async def test_proactive_notifications_feed_and_lifecycle(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Test notification list, mark as read, dismiss, and snooze."""
    user = await create_user(test_db, "feed_user@example.com")
    authenticate_client(async_client, user)

    # Create test notifications
    now = datetime.now(timezone.utc)
    notif1 = Notification(
        user_id=user.id,
        title="Task Due Soon",
        message="Prepare deck is due in 30 minutes",
        notification_type="task_due_soon",
        priority="HIGH",
        source_type="task",
        source_id="task-123",
        status="unread",
        idempotency_key=f"proactive:{user.id}:task:task_due_soon:task-123:bucket1",
        metadata_json={
            "suggested_actions": [
                {
                    "action_type": "view_task",
                    "target_resource": "task",
                    "target_id": "task-123",
                    "risk_level": "READ",
                    "display_label": "View Task",
                    "action_payload": {"task_id": "task-123"},
                }
            ]
        },
    )
    notif2 = Notification(
        user_id=user.id,
        title="Meeting Soon",
        message="Sync in 10 mins",
        notification_type="meeting_soon",
        priority="MEDIUM",
        source_type="calendar",
        source_id="event-456",
        status="unread",
        idempotency_key=f"proactive:{user.id}:calendar:meeting_soon:event-456:bucket1",
    )
    test_db.add_all([notif1, notif2])
    await test_db.commit()
    await test_db.refresh(notif1)
    await test_db.refresh(notif2)

    # 1. Fetch notifications
    resp = await async_client.get("/api/v1/proactive/notifications")
    assert resp.status_code == 200
    feed = resp.json()
    assert len(feed) == 2
    assert feed[0]["id"] in [str(notif1.id), str(notif2.id)]

    # 2. Mark as read
    resp = await async_client.post(f"/api/v1/proactive/notifications/{notif1.id}/read")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["read"] is True

    # 3. Snooze notif2 by 30 mins
    resp = await async_client.post(
        f"/api/v1/proactive/notifications/{notif2.id}/snooze",
        json={"snooze_minutes": 30},
    )
    assert resp.status_code == 200
    assert resp.json()["snoozed"] is True
    assert resp.json()["snoozed_until"] is not None

    # Fetching active notifications should now exclude snoozed notif2
    resp = await async_client.get("/api/v1/proactive/notifications?active_only=true")
    assert resp.status_code == 200
    active_feed = resp.json()
    assert len(active_feed) == 1
    assert active_feed[0]["id"] == str(notif1.id)

    # 4. Dismiss notif1
    resp = await async_client.post(f"/api/v1/proactive/notifications/{notif1.id}/dismiss")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["dismissed"] is True

    # Active feed should now be empty
    resp = await async_client.get("/api/v1/proactive/notifications?active_only=true")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_proactive_notification_idor_defense(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """User B cannot read, dismiss, or snooze User A's notifications."""
    user_a = await create_user(test_db, "user_a@example.com")
    user_b = await create_user(test_db, "user_b@example.com")
    authenticate_client(async_client, user_b)

    notif_a = Notification(
        user_id=user_a.id,
        title="User A Private Alert",
        message="Secret",
        notification_type="task_overdue",
        priority="HIGH",
        source_type="task",
        source_id="task-secret",
        status="unread",
        idempotency_key=f"proactive:{user_a.id}:task:task_overdue:task-secret:bucket1",
    )
    test_db.add(notif_a)
    await test_db.commit()
    await test_db.refresh(notif_a)

    # Attempt to read User A's notification with User B's session
    resp = await async_client.post(f"/api/v1/proactive/notifications/{notif_a.id}/read")
    assert resp.status_code == 404

    # Attempt to snooze User A's notification
    resp = await async_client.post(
        f"/api/v1/proactive/notifications/{notif_a.id}/snooze",
        json={"snooze_minutes": 15},
    )
    assert resp.status_code == 404

    # Attempt to dismiss User A's notification
    resp = await async_client.post(f"/api/v1/proactive/notifications/{notif_a.id}/dismiss")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_proactive_execute_read_action(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Low/read risk suggested action executes immediately via ToolExecutor."""
    user = await create_user(test_db, "action_user@example.com")
    authenticate_client(async_client, user)

    task = Task(
        user_id=user.id,
        title="Finish M8 Tests",
        priority="high",
        status="pending",
    )
    test_db.add(task)
    await test_db.commit()
    await test_db.refresh(task)

    notif = Notification(
        user_id=user.id,
        title="Task Check",
        message="Check task",
        notification_type="task_due_soon",
        priority="HIGH",
        status="unread",
        idempotency_key=f"proactive:{user.id}:task:task_due_soon:{task.id}:bucket1",
    )
    test_db.add(notif)
    await test_db.commit()
    await test_db.refresh(notif)

    payload = {
        "notification_id": str(notif.id),
        "action_type": "view_task",
        "action_payload": {"task_id": str(task.id)},
    }
    resp = await async_client.post("/api/v1/proactive/actions/execute", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "success"
    assert "Finish M8 Tests" in str(res["result"])


@pytest.mark.asyncio
async def test_proactive_execute_high_risk_action_requires_confirmation(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """High-risk action (e.g. delete_task) requires confirmation challenge."""
    user = await create_user(test_db, "high_risk_user@example.com")
    authenticate_client(async_client, user)

    task = Task(
        user_id=user.id,
        title="Deploy to Prod",
        priority="high",
        status="pending",
    )
    test_db.add(task)
    await test_db.commit()
    await test_db.refresh(task)

    notif = Notification(
        user_id=user.id,
        title="Clean up old task",
        message="Delete task",
        notification_type="task_overdue",
        priority="HIGH",
        status="unread",
        idempotency_key=f"proactive:{user.id}:task:task_overdue:{task.id}:bucket1",
    )
    test_db.add(notif)
    await test_db.commit()
    await test_db.refresh(notif)

    payload = {
        "notification_id": str(notif.id),
        "action_type": "delete_task",
        "action_payload": {"task_id": str(task.id)},
    }

    # First attempt without confirmation token should return confirmation_required
    resp = await async_client.post("/api/v1/proactive/actions/execute", json=payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] == "confirmation_required"
    assert res["confirmation_token"] is not None

    raw_token = res["confirmation_token"]

    # Second attempt with confirmation token
    payload_with_token = {
        **payload,
        "confirmation_token": raw_token,
    }
    resp2 = await async_client.post("/api/v1/proactive/actions/execute", json=payload_with_token)
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["status"] == "success"

    # Task should be deleted
    deleted_task = await test_db.get(Task, task.id)
    assert deleted_task is None


@pytest.mark.asyncio
async def test_proactive_trigger_check_endpoint(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Trigger manual proactive evaluation check for current authenticated user."""
    user = await create_user(test_db, "trigger_user@example.com")
    authenticate_client(async_client, user)

    # Enable proactive monitoring
    pref = UserPreference(
        user_id=user.id,
        proactive_enabled=True,
        task_alerts_enabled=True,
        calendar_alerts_enabled=False,
        reminder_alerts_enabled=False,
        email_alerts_enabled=False,
        quiet_hours_enabled=False,
    )
    test_db.add(pref)

    # Create an overdue task
    past_due = datetime.now(timezone.utc) - timedelta(hours=2)
    task = Task(
        user_id=user.id,
        title="Urgent Bug Fix",
        priority="high",
        status="pending",
        due_at=past_due,
    )
    test_db.add(task)
    await test_db.commit()

    resp = await async_client.post("/api/v1/proactive/trigger-check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["notifications_created"] >= 1
