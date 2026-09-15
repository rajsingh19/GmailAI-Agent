"""
Tests for AI Agent Tools and Tool Registry (Milestone 6).
Verifies:
- Tool registration, inspection, and schema generation
- Task tools (create, list, get, update, complete, delete)
- Reminder tools (create, list, get, snooze, cancel, delete)
- Notification tools (list, mark_read, mark_all_read)
- Gmail read-only tools with untrusted tagging
- Calendar read-only tools with untrusted tagging
- Session user_id injection and multi-user isolation
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.task import Task
from app.models.reminder import Reminder
from app.models.notification import Notification
from app.ai.agent.tool_registry import ToolRegistry, RiskLevel, ToolDefinition
from app.ai.tools.task_tools import (
    execute_create_task,
    execute_list_tasks,
    execute_get_task,
    execute_update_task,
    execute_complete_task,
    execute_delete_task,
)
from app.ai.tools.reminder_tools import (
    execute_create_reminder,
    execute_list_reminders,
    execute_get_reminder,
    execute_snooze_reminder,
    execute_cancel_reminder,
    execute_delete_reminder,
)
from app.ai.tools.notification_tools import (
    execute_list_notifications,
    execute_mark_notification_read,
    execute_mark_all_notifications_read,
)
from app.ai.tools.gmail_tools import (
    execute_get_gmail_profile,
    execute_search_gmail,
    execute_list_gmail_messages,
    execute_get_gmail_message,
)
from app.ai.tools.calendar_tools import (
    execute_list_calendars,
    execute_get_calendar,
    execute_list_calendar_events,
    execute_get_calendar_event,
)
from app.schemas.gmail import GmailProfileResponse, GmailMessageSummary, GmailMessageDetail
from app.schemas.calendar import CalendarSummary, CalendarDetail, CalendarEventSummary, CalendarEventDetail


async def create_test_user(test_db: AsyncSession, email: str = "agent_tool_user@example.com") -> User:
    user = User(email=email, full_name="Agent Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def test_tool_registry_management():
    """Verify tool registry registers tools, exposes schemas, and lists registered tools."""
    tools = ToolRegistry.list_tools()
    assert len(tools) == 24

    create_task_tool = ToolRegistry.get("create_task")
    assert create_task_tool is not None
    assert create_task_tool.risk_level == RiskLevel.LOW_RISK_WRITE
    assert create_task_tool.func is not None

    delete_task_tool = ToolRegistry.get("delete_task")
    assert delete_task_tool is not None
    assert delete_task_tool.risk_level == RiskLevel.HIGH_RISK_WRITE

    search_gmail_tool = ToolRegistry.get("search_gmail")
    assert search_gmail_tool is not None
    assert search_gmail_tool.risk_level == RiskLevel.READ

    assert ToolRegistry.get("non_existent_tool_123") is None

    declarations = ToolRegistry.get_tool_declarations()
    assert len(declarations) == 24
    names = [d.name for d in declarations]
    assert "create_task" in names
    assert "list_tasks" in names
    assert "delete_task" in names
    assert "search_gmail" in names
    assert "list_calendar_events" in names


@pytest.mark.asyncio
async def test_task_tools_lifecycle(test_db: AsyncSession):
    """Verify task tools CRUD lifecycle through AI tool handlers."""
    test_user = await create_test_user(test_db, "task_life@example.com")

    # 1. Create task
    create_res = await execute_create_task(
        user_id=test_user.id,
        db=test_db,
        title="AI Generated Task",
        description="Follow up on roadmap",
        priority="high",
        due_at=datetime.now(timezone.utc).isoformat(),
        timezone="UTC"
    )
    assert create_res["status"] == "success"
    task_id = create_res["task"]["id"]
    assert create_res["task"]["title"] == "AI Generated Task"
    assert create_res["task"]["priority"] == "high"

    # 2. Get task
    get_res = await execute_get_task(user_id=test_user.id, db=test_db, task_id=task_id)
    assert get_res["status"] == "success"
    assert get_res["task"]["id"] == task_id

    # 3. Update task
    update_res = await execute_update_task(
        user_id=test_user.id,
        db=test_db,
        task_id=task_id,
        title="Updated Task Title",
        priority="medium"
    )
    assert update_res["status"] == "success"
    assert update_res["task"]["title"] == "Updated Task Title"
    assert update_res["task"]["priority"] == "medium"

    # 4. List tasks
    list_res = await execute_list_tasks(user_id=test_user.id, db=test_db, status="pending")
    assert list_res["status"] == "success"
    assert list_res["total"] >= 1
    assert any(t["id"] == task_id for t in list_res["tasks"])

    # 5. Complete task
    comp_res = await execute_complete_task(user_id=test_user.id, db=test_db, task_id=task_id)
    assert comp_res["status"] == "success"
    assert comp_res["task_id"] == task_id

    # 6. Delete task
    del_res = await execute_delete_task(user_id=test_user.id, db=test_db, task_id=task_id)
    assert del_res["status"] == "success"

    # Verify task no longer exists
    get_after_del = await execute_get_task(user_id=test_user.id, db=test_db, task_id=task_id)
    assert get_after_del["status"] == "error"


@pytest.mark.asyncio
async def test_task_tools_user_isolation(test_db: AsyncSession):
    """Verify task tools enforce strict isolation between users."""
    test_user1 = await create_test_user(test_db, "user1_iso@example.com")
    test_user2 = await create_test_user(test_db, "user2_iso@example.com")

    create_res = await execute_create_task(
        user_id=test_user1.id,
        db=test_db,
        title="User 1 Private Task"
    )
    task_id = create_res["task"]["id"]

    # User 2 cannot get User 1's task
    get_res = await execute_get_task(user_id=test_user2.id, db=test_db, task_id=task_id)
    assert get_res["status"] == "error"

    # User 2 cannot update User 1's task
    update_res = await execute_update_task(user_id=test_user2.id, db=test_db, task_id=task_id, title="Hacked")
    assert update_res["status"] == "error"

    # User 2 cannot complete User 1's task
    comp_res = await execute_complete_task(user_id=test_user2.id, db=test_db, task_id=task_id)
    assert comp_res["status"] == "error"

    # User 2 cannot delete User 1's task
    del_res = await execute_delete_task(user_id=test_user2.id, db=test_db, task_id=task_id)
    assert del_res["status"] == "error"


@pytest.mark.asyncio
async def test_reminder_tools_lifecycle(test_db: AsyncSession):
    """Verify reminder tools CRUD, snooze, and cancel lifecycles."""
    test_user = await create_test_user(test_db, "rem_life@example.com")
    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    # 1. Create reminder
    create_res = await execute_create_reminder(
        user_id=test_user.id,
        db=test_db,
        title="Team Standup Reminder",
        remind_at=future_time,
        timezone="UTC"
    )
    assert create_res["status"] == "success"
    rem_id = create_res["reminder"]["id"]

    # 2. Get reminder
    get_res = await execute_get_reminder(user_id=test_user.id, db=test_db, reminder_id=rem_id)
    assert get_res["status"] == "success"
    assert get_res["reminder"]["id"] == rem_id

    # 3. List reminders
    list_res = await execute_list_reminders(user_id=test_user.id, db=test_db, status="scheduled")
    assert list_res["status"] == "success"
    assert list_res["total"] >= 1
    assert any(r["id"] == rem_id for r in list_res["reminders"])

    # 4. Snooze reminder
    snooze_res = await execute_snooze_reminder(user_id=test_user.id, db=test_db, reminder_id=rem_id, duration="30m")
    assert snooze_res["status"] == "success"
    assert "snoozed" in snooze_res["message"].lower()

    # 5. Cancel reminder
    cancel_res = await execute_cancel_reminder(user_id=test_user.id, db=test_db, reminder_id=rem_id)
    assert cancel_res["status"] == "success"
    assert "cancelled" in cancel_res["message"].lower()

    # 6. Delete reminder
    del_res = await execute_delete_reminder(user_id=test_user.id, db=test_db, reminder_id=rem_id)
    assert del_res["status"] == "success"


@pytest.mark.asyncio
async def test_notification_tools_lifecycle(test_db: AsyncSession):
    """Verify notification tools read and mark read operations."""
    test_user = await create_test_user(test_db, "notif_tool@example.com")
    # Seed a notification directly
    notif = Notification(
        user_id=test_user.id,
        idempotency_key=f"agent-test-{datetime.now(timezone.utc).timestamp()}",
        title="System Notice",
        message="Your scheduled report is ready",
        status="unread"
    )
    test_db.add(notif)
    await test_db.commit()
    await test_db.refresh(notif)

    # 1. List notifications
    list_res = await execute_list_notifications(user_id=test_user.id, db=test_db, status="unread")
    assert list_res["status"] == "success"
    assert list_res["unread_count"] >= 1
    assert any(n["id"] == notif.id for n in list_res["notifications"])

    # 2. Mark single notification read
    read_res = await execute_mark_notification_read(user_id=test_user.id, db=test_db, notification_id=notif.id)
    assert read_res["status"] == "success"

    # 3. Mark all notifications read
    read_all_res = await execute_mark_all_notifications_read(user_id=test_user.id, db=test_db)
    assert read_all_res["status"] == "success"
    assert "marked_count" in read_all_res


@pytest.mark.asyncio
async def test_gmail_read_tools_with_untrusted_tagging(test_db: AsyncSession):
    """Verify Gmail read tools tag output as untrusted and return structured summaries."""
    test_user = await create_test_user(test_db, "gmail_tool_user@example.com")
    mock_profile = GmailProfileResponse(
        email=test_user.email,
        messages_total=42,
        threads_total=18,
        history_id="12345"
    )

    mock_msg_summary = GmailMessageSummary(
        id="msg-101",
        thread_id="th-101",
        subject="Project Update",
        sender="boss@example.com",
        recipients=[test_user.email],
        timestamp="2026-09-15T10:00:00Z",
        snippet="Here is the status...",
        labels=["INBOX", "UNREAD"],
        is_unread=True,
        has_attachments=False
    )

    mock_msg_list_resp = ([mock_msg_summary], None)

    mock_msg_detail = GmailMessageDetail(
        id="msg-101",
        thread_id="th-101",
        subject="Project Update",
        sender="boss@example.com",
        recipients=[test_user.email],
        cc=[],
        bcc=[],
        timestamp="2026-09-15T10:00:00Z",
        snippet="Here is the status...",
        body_plain="Please review the attached quarterly metrics.",
        body_html_text=None,
        labels=["INBOX"],
        is_unread=False,
        attachments=[]
    )

    with patch("app.services.gmail_service.GmailService.get_profile", new_callable=AsyncMock) as mock_get_prof, \
         patch("app.services.gmail_service.GmailService.list_messages", new_callable=AsyncMock) as mock_list_msg, \
         patch("app.services.gmail_service.GmailService.get_message", new_callable=AsyncMock) as mock_get_msg:

        from app.schemas.gmail import GmailMessageListResponse
        mock_get_prof.return_value = mock_profile
        mock_list_msg.return_value = GmailMessageListResponse(messages=[mock_msg_summary], next_page_token=None, result_size_estimate=1)
        mock_get_msg.return_value = mock_msg_detail

        # 1. Profile tool
        prof_res = await execute_get_gmail_profile(user_id=test_user.id, db=test_db)
        assert prof_res["status"] == "success"
        assert prof_res["profile"]["email"] == test_user.email
        assert prof_res["profile"]["messages_total"] == 42

        # 2. Search tool
        search_res = await execute_search_gmail(user_id=test_user.id, db=test_db, query="is:unread", max_results=5)
        assert search_res["status"] == "success"
        assert search_res["source"] == "gmail"
        assert search_res["trusted"] is False
        assert len(search_res["messages"]) == 1
        assert search_res["messages"][0]["id"] == "msg-101"

        # 3. List messages tool
        list_res = await execute_list_gmail_messages(user_id=test_user.id, db=test_db, max_results=10)
        assert list_res["status"] == "success"
        assert list_res["source"] == "gmail"
        assert list_res["trusted"] is False
        assert len(list_res["messages"]) == 1

        # 4. Message detail tool
        detail_res = await execute_get_gmail_message(user_id=test_user.id, db=test_db, message_id="msg-101")
        assert detail_res["status"] == "success"
        assert detail_res["source"] == "gmail"
        assert detail_res["trusted"] is False
        assert detail_res["message"]["subject"] == "Project Update"
        assert "quarterly metrics" in detail_res["message"]["body"]


@pytest.mark.asyncio
async def test_calendar_read_tools_with_untrusted_tagging(test_db: AsyncSession):
    """Verify Calendar read tools tag external descriptions as untrusted."""
    test_user = await create_test_user(test_db, "cal_tool_user@example.com")
    mock_cal_summary = CalendarSummary(
        id="primary",
        summary=test_user.email,
        description="Main calendar",
        time_zone="UTC",
        primary=True,
        selected=True,
        hidden=False
    )

    mock_cal_detail = CalendarDetail(
        id="primary",
        summary=test_user.email,
        description="Main calendar",
        location=None,
        time_zone="UTC",
        primary=True,
        access_role="owner",
        selected=True,
        hidden=False
    )

    mock_event_summary = CalendarEventSummary(
        id="evt-101",
        calendar_id="primary",
        summary="Sprint Planning",
        description="Discuss sprint backlog",
        location="Room 402",
        start="2026-09-15T14:00:00Z",
        end="2026-09-15T15:00:00Z",
        time_zone="UTC",
        status="confirmed",
        html_link="https://calendar.google.com/event?id=evt-101",
        organizer="scrum@example.com",
        attendees_count=4,
        is_all_day=False,
        has_conference=False,
        conference_uri=None
    )

    mock_event_detail = CalendarEventDetail(
        id="evt-101",
        calendar_id="primary",
        summary="Sprint Planning",
        description="Discuss sprint backlog",
        location="Room 402",
        start="2026-09-15T14:00:00Z",
        end="2026-09-15T15:00:00Z",
        time_zone="UTC",
        status="confirmed",
        html_link="https://calendar.google.com/event?id=evt-101",
        organizer="scrum@example.com",
        creator="scrum@example.com",
        attendees=[],
        conference=None,
        recurrence=[],
        is_all_day=False
    )

    with patch("app.services.calendar_service.CalendarService.get_calendar_list", new_callable=AsyncMock) as mock_list_cal, \
         patch("app.services.calendar_service.CalendarService.get_calendar", new_callable=AsyncMock) as mock_get_cal, \
         patch("app.services.calendar_service.CalendarService.list_events", new_callable=AsyncMock) as mock_list_evt, \
         patch("app.services.calendar_service.CalendarService.get_event", new_callable=AsyncMock) as mock_get_evt:

        from app.schemas.calendar import CalendarListResponse, CalendarEventListResponse
        mock_list_cal.return_value = CalendarListResponse(calendars=[mock_cal_summary], next_page_token=None)
        mock_get_cal.return_value = mock_cal_detail
        mock_list_evt.return_value = CalendarEventListResponse(events=[mock_event_summary], next_page_token=None, calendar_id="primary")
        mock_get_evt.return_value = mock_event_detail

        # 1. List calendars tool
        cals_res = await execute_list_calendars(user_id=test_user.id, db=test_db)
        assert cals_res["status"] == "success"
        assert len(cals_res["calendars"]) == 1
        assert cals_res["calendars"][0]["id"] == "primary"

        # 2. Get calendar detail tool
        cal_detail_res = await execute_get_calendar(user_id=test_user.id, db=test_db, calendar_id="primary")
        assert cal_detail_res["status"] == "success"
        assert cal_detail_res["calendar"]["id"] == "primary"

        # 3. List calendar events tool
        evts_res = await execute_list_calendar_events(user_id=test_user.id, db=test_db, calendar_id="primary")
        assert evts_res["status"] == "success"
        assert evts_res["source"] == "calendar"
        assert evts_res["trusted"] is False
        assert len(evts_res["events"]) == 1
        assert evts_res["events"][0]["id"] == "evt-101"

        # 4. Event detail tool
        evt_detail_res = await execute_get_calendar_event(user_id=test_user.id, db=test_db, calendar_id="primary", event_id="evt-101")
        assert evt_detail_res["status"] == "success"
        assert evt_detail_res["source"] == "calendar"
        assert evt_detail_res["trusted"] is False
        assert evt_detail_res["event"]["summary"] == "Sprint Planning"
        assert "sprint backlog" in evt_detail_res["event"]["description"]


@pytest.mark.asyncio
async def test_task_tools_edge_cases_and_missing_resources(test_db: AsyncSession):
    """Verify task tools handle invalid inputs and non-existent IDs gracefully."""
    test_user = await create_test_user(test_db, "task_edge@example.com")

    # Invalid datetime format in create
    res_bad_dt = await execute_create_task(
        user_id=test_user.id,
        db=test_db,
        title="Bad Date Task",
        due_at="not-a-valid-iso-date"
    )
    assert res_bad_dt["status"] == "error"
    assert "invalid due_at" in res_bad_dt["message"].lower()

    # Get non-existent
    res_not_found = await execute_get_task(user_id=test_user.id, db=test_db, task_id="non-existent-uuid")
    assert res_not_found["status"] == "error"

    # Update non-existent
    res_upd_missing = await execute_update_task(user_id=test_user.id, db=test_db, task_id="non-existent-uuid", title="New")
    assert res_upd_missing["status"] == "error"

    # Complete non-existent
    res_comp_missing = await execute_complete_task(user_id=test_user.id, db=test_db, task_id="non-existent-uuid")
    assert res_comp_missing["status"] == "error"

    # Delete non-existent
    res_del_missing = await execute_delete_task(user_id=test_user.id, db=test_db, task_id="non-existent-uuid")
    assert res_del_missing["status"] == "error"


@pytest.mark.asyncio
async def test_reminder_tools_edge_cases_and_presets(test_db: AsyncSession):
    """Verify reminder tools handle invalid inputs and multiple snooze presets."""
    test_user = await create_test_user(test_db, "rem_edge@example.com")

    # Invalid datetime format in create
    res_bad_dt = await execute_create_reminder(
        user_id=test_user.id,
        db=test_db,
        title="Bad Reminder",
        remind_at="invalid-date"
    )
    assert res_bad_dt["status"] == "error"

    # Create valid reminder
    future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    create_res = await execute_create_reminder(
        user_id=test_user.id,
        db=test_db,
        title="Preset Reminder",
        remind_at=future_time
    )
    rem_id = create_res["reminder"]["id"]

    # Snooze with 1h preset
    snooze_1h = await execute_snooze_reminder(user_id=test_user.id, db=test_db, reminder_id=rem_id, duration="1h")
    assert snooze_1h["status"] == "success"

    # Snooze with 1d preset
    snooze_1d = await execute_snooze_reminder(user_id=test_user.id, db=test_db, reminder_id=rem_id, duration="1d")
    assert snooze_1d["status"] == "success"

    # Snooze non-existent
    res_snooze_missing = await execute_snooze_reminder(user_id=test_user.id, db=test_db, reminder_id="missing-id")
    assert res_snooze_missing["status"] == "error"

    # Cancel non-existent
    res_cancel_missing = await execute_cancel_reminder(user_id=test_user.id, db=test_db, reminder_id="missing-id")
    assert res_cancel_missing["status"] == "error"

    # Delete non-existent
    res_del_missing = await execute_delete_reminder(user_id=test_user.id, db=test_db, reminder_id="missing-id")
    assert res_del_missing["status"] == "error"


@pytest.mark.asyncio
async def test_reminder_tools_cross_user_isolation(test_db: AsyncSession):
    """Verify reminder tools strictly prevent cross-user mutations."""
    user1 = await create_test_user(test_db, "rem_user1@example.com")
    user2 = await create_test_user(test_db, "rem_user2@example.com")

    future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    create_res = await execute_create_reminder(user_id=user1.id, db=test_db, title="User1 Secret Reminder", remind_at=future_time)
    rem_id = create_res["reminder"]["id"]

    # User 2 cannot get user 1's reminder
    get_res = await execute_get_reminder(user_id=user2.id, db=test_db, reminder_id=rem_id)
    assert get_res["status"] == "error"

    # User 2 cannot snooze user 1's reminder
    snooze_res = await execute_snooze_reminder(user_id=user2.id, db=test_db, reminder_id=rem_id)
    assert snooze_res["status"] == "error"

    # User 2 cannot cancel user 1's reminder
    cancel_res = await execute_cancel_reminder(user_id=user2.id, db=test_db, reminder_id=rem_id)
    assert cancel_res["status"] == "error"

    # User 2 cannot delete user 1's reminder
    del_res = await execute_delete_reminder(user_id=user2.id, db=test_db, reminder_id=rem_id)
    assert del_res["status"] == "error"


@pytest.mark.asyncio
async def test_notification_tools_cross_user_isolation(test_db: AsyncSession):
    """Verify notification tools enforce multi-user boundaries."""
    user1 = await create_test_user(test_db, "notif_user1@example.com")
    user2 = await create_test_user(test_db, "notif_user2@example.com")

    notif = Notification(
        user_id=user1.id,
        idempotency_key="iso-key-101",
        title="User1 Alert",
        message="Private alert text",
        status="unread"
    )
    test_db.add(notif)
    await test_db.commit()

    # User 2 lists notifications -> should not see user 1's notification
    u2_list = await execute_list_notifications(user_id=user2.id, db=test_db)
    assert u2_list["unread_count"] == 0
    assert not any(n["id"] == notif.id for n in u2_list["notifications"])

    # User 2 cannot mark user 1's notification as read
    u2_read = await execute_mark_notification_read(user_id=user2.id, db=test_db, notification_id=notif.id)
    assert u2_read["status"] == "error"


@pytest.mark.asyncio
async def test_gmail_tools_error_handling(test_db: AsyncSession):
    """Verify Gmail read tools return clean, structured error messages without crashing."""
    from app.services.gmail_service import GmailNotConnectedError, GmailAuthenticationError, GmailNotFoundError
    test_user = await create_test_user(test_db, "gmail_err@example.com")

    with patch("app.services.gmail_service.GmailService.get_profile", side_effect=GmailNotConnectedError("Not connected")):
        res = await execute_get_gmail_profile(user_id=test_user.id, db=test_db)
        assert res["status"] == "error"
        assert "not connected" in res["message"].lower()

    with patch("app.services.gmail_service.GmailService.list_messages", side_effect=GmailAuthenticationError("Auth expired")):
        res = await execute_search_gmail(user_id=test_user.id, db=test_db, query="test")
        assert res["status"] == "error"
        assert "expired" in res["message"].lower()

    with patch("app.services.gmail_service.GmailService.get_message", side_effect=GmailNotFoundError("Not found")):
        res = await execute_get_gmail_message(user_id=test_user.id, db=test_db, message_id="missing-msg")
        assert res["status"] == "error"
        assert "not found" in res["message"].lower()


@pytest.mark.asyncio
async def test_calendar_tools_error_handling(test_db: AsyncSession):
    """Verify Calendar read tools return clean, structured error messages on domain exceptions."""
    from app.services.calendar_service import CalendarNotConnectedError, CalendarScopeMissingError, CalendarNotFoundError
    test_user = await create_test_user(test_db, "cal_err@example.com")

    with patch("app.services.calendar_service.CalendarService.get_calendar_list", side_effect=CalendarNotConnectedError("Not connected")):
        res = await execute_list_calendars(user_id=test_user.id, db=test_db)
        assert res["status"] == "error"
        assert "not connected" in res["message"].lower()

    with patch("app.services.calendar_service.CalendarService.list_events", side_effect=CalendarScopeMissingError("Scope missing")):
        res = await execute_list_calendar_events(user_id=test_user.id, db=test_db)
        assert res["status"] == "error"
        assert "missing" in res["message"].lower()

    with patch("app.services.calendar_service.CalendarService.get_event", side_effect=CalendarNotFoundError("Event not found")):
        res = await execute_get_calendar_event(user_id=test_user.id, db=test_db, calendar_id="primary", event_id="missing-evt")
        assert res["status"] == "error"


def test_gmail_and_calendar_write_operations_strictly_prohibited():
    """Verify that no Gmail or Calendar write/mutation tools are registered in Milestone 6."""
    all_tools = ToolRegistry.list_tools()
    all_names = [t.name for t in all_tools]

    # Prohibited Gmail write tools
    assert "send_email" not in all_names
    assert "send_gmail_message" not in all_names
    assert "delete_email" not in all_names
    assert "delete_gmail_message" not in all_names
    assert "modify_gmail_labels" not in all_names

    # Prohibited Calendar write tools
    assert "create_calendar_event" not in all_names
    assert "create_event" not in all_names
    assert "update_calendar_event" not in all_names
    assert "delete_calendar_event" not in all_names
    assert "delete_event" not in all_names


@pytest.mark.asyncio
async def test_task_tools_priority_and_status_filtering(test_db: AsyncSession):
    """Verify task tools support multi-field filtering by priority and status."""
    test_user = await create_test_user(test_db, "task_filter_user@example.com")

    # Create tasks with different priority & status
    await execute_create_task(user_id=test_user.id, db=test_db, title="T1", priority="high")
    t2 = await execute_create_task(user_id=test_user.id, db=test_db, title="T2", priority="low")
    await execute_complete_task(user_id=test_user.id, db=test_db, task_id=t2["task"]["id"])

    # Filter high priority
    res_high = await execute_list_tasks(user_id=test_user.id, db=test_db, priority="high")
    assert res_high["status"] == "success"
    assert any(t["title"] == "T1" for t in res_high["tasks"])

    # Filter completed status
    res_completed = await execute_list_tasks(user_id=test_user.id, db=test_db, status="completed")
    assert res_completed["status"] == "success"
    assert any(t["title"] == "T2" for t in res_completed["tasks"])



