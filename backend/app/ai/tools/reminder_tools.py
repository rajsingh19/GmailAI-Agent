from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolDefinition, ToolRegistry, RiskLevel
from app.services.reminder_service import ReminderService
from app.schemas.reminder import ReminderCreate, ReminderSnooze


async def execute_create_reminder(
    user_id: str,
    db: AsyncSession,
    title: str,
    remind_at: str,
    message: Optional[str] = None,
    timezone: Optional[str] = "UTC",
    recurrence_rule: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tool function to schedule a new one-time or recurring reminder."""
    try:
        parsed = datetime.fromisoformat(remind_at)
        remind_dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return {"status": "error", "message": f"Invalid remind_at ISO format: {remind_at}"}

    try:
        rem_in = ReminderCreate(
            title=title,
            message=message,
            remind_at=remind_dt,
            timezone=timezone or "UTC",
            recurrence_rule=recurrence_rule,
            task_id=task_id,
        )
        reminder = await ReminderService.create_reminder(db=db, user_id=user_id, reminder_in=rem_in)
        return {
            "status": "success",
            "reminder": {
                "id": reminder.id,
                "title": reminder.title,
                "remind_at": reminder.remind_at.isoformat(),
                "next_trigger_at": reminder.next_trigger_at.isoformat() if reminder.next_trigger_at else None,
                "status": reminder.status,
                "recurrence": reminder.recurrence_rule,
            },
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def execute_list_reminders(
    user_id: str,
    db: AsyncSession,
    status: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: Optional[int] = 10,
) -> Dict[str, Any]:
    """Tool function to list reminders."""
    lim = min(max(limit or 10, 1), 20)
    reminders, total = await ReminderService.list_reminders(
        db=db, user_id=user_id, status=status, task_id=task_id, limit=lim, offset=0
    )
    items = [
        {
            "id": r.id,
            "title": r.title,
            "status": r.status,
            "next_trigger_at": r.next_trigger_at.isoformat() if r.next_trigger_at else None,
            "recurrence": r.recurrence_rule,
            "message": r.message,
        }
        for r in reminders
    ]
    return {
        "status": "success",
        "total": total,
        "count": len(items),
        "reminders": items,
    }


async def execute_get_reminder(
    user_id: str,
    db: AsyncSession,
    reminder_id: str,
) -> Dict[str, Any]:
    """Tool function to retrieve details of a specific reminder."""
    reminder = await ReminderService.get_reminder(db=db, user_id=user_id, reminder_id=reminder_id)
    if not reminder:
        return {"status": "error", "message": f"Reminder with ID '{reminder_id}' not found."}

    return {
        "status": "success",
        "reminder": {
            "id": reminder.id,
            "title": reminder.title,
            "message": reminder.message,
            "status": reminder.status,
            "remind_at": reminder.remind_at.isoformat(),
            "next_trigger_at": reminder.next_trigger_at.isoformat() if reminder.next_trigger_at else None,
            "recurrence": reminder.recurrence_rule,
            "task_id": reminder.task_id,
        },
    }


async def execute_snooze_reminder(
    user_id: str,
    db: AsyncSession,
    reminder_id: str,
    duration: Optional[str] = "15m",
) -> Dict[str, Any]:
    """Tool function to snooze a reminder (5m, 15m, 30m, 1h, 1d)."""
    try:
        snooze_in = ReminderSnooze(duration=duration)
        reminder = await ReminderService.snooze_reminder(
            db=db, user_id=user_id, reminder_id=reminder_id, snooze_in=snooze_in
        )
        if not reminder:
            return {"status": "error", "message": f"Reminder with ID '{reminder_id}' not found."}

        return {
            "status": "success",
            "message": f"Reminder '{reminder.title}' snoozed until {reminder.next_trigger_at.isoformat() if reminder.next_trigger_at else 'later'}.",
            "snoozed_until": reminder.snoozed_until.isoformat() if reminder.snoozed_until else None,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def execute_cancel_reminder(
    user_id: str,
    db: AsyncSession,
    reminder_id: str,
) -> Dict[str, Any]:
    """Tool function to cancel a reminder."""
    reminder = await ReminderService.cancel_reminder(db=db, user_id=user_id, reminder_id=reminder_id)
    if not reminder:
        return {"status": "error", "message": f"Reminder with ID '{reminder_id}' not found."}

    return {
        "status": "success",
        "message": f"Reminder '{reminder.title}' cancelled.",
        "reminder_id": reminder.id,
    }


async def execute_delete_reminder(
    user_id: str,
    db: AsyncSession,
    reminder_id: str,
) -> Dict[str, Any]:
    """Tool function to delete a reminder. Classified as HIGH_RISK_WRITE."""
    deleted = await ReminderService.delete_reminder(db=db, user_id=user_id, reminder_id=reminder_id)
    if not deleted:
        return {"status": "error", "message": f"Reminder with ID '{reminder_id}' not found."}

    return {
        "status": "success",
        "message": f"Reminder with ID '{reminder_id}' deleted successfully.",
        "reminder_id": reminder_id,
    }


def register_reminder_tools() -> None:
    """Registers all reminder tools into ToolRegistry."""
    ToolRegistry.register(
        ToolDefinition(
            name="create_reminder",
            description="Schedule a new timed or recurring alert/reminder for the user.",
            friendly_name="Scheduling reminder",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_create_reminder,
            parameters_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Reminder title/summary"},
                    "remind_at": {"type": "string", "description": "ISO 8601 target trigger timestamp"},
                    "message": {"type": "string", "description": "Optional notes or message body"},
                    "timezone": {"type": "string", "description": "IANA timezone name (default 'UTC')"},
                    "recurrence_rule": {"type": "string", "description": "Optional RFC 5545 RRULE (e.g. 'FREQ=DAILY')"},
                    "task_id": {"type": "string", "description": "Optional associated Task ID"},
                },
                "required": ["title", "remind_at"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="list_reminders",
            description="List user reminders with optional status filtering.",
            friendly_name="Listing reminders",
            risk_level=RiskLevel.READ,
            func=execute_list_reminders,
            parameters_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status (scheduled, snoozed, triggered, cancelled)"},
                    "limit": {"type": "integer", "description": "Max reminders to return (default 10, max 20)"},
                },
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="get_reminder",
            description="Retrieve details of a specific reminder by ID.",
            friendly_name="Fetching reminder details",
            risk_level=RiskLevel.READ,
            func=execute_get_reminder,
            parameters_schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Unique reminder ID"},
                },
                "required": ["reminder_id"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="snooze_reminder",
            description="Snooze an active reminder for a given preset duration (5m, 15m, 30m, 1h, 1d).",
            friendly_name="Snoozing reminder",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_snooze_reminder,
            parameters_schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Unique reminder ID"},
                    "duration": {"type": "string", "enum": ["5m", "15m", "30m", "1h", "1d"], "description": "Snooze duration"},
                },
                "required": ["reminder_id"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="cancel_reminder",
            description="Cancel a scheduled reminder so it will not trigger.",
            friendly_name="Cancelling reminder",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_cancel_reminder,
            parameters_schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Unique reminder ID"},
                },
                "required": ["reminder_id"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="delete_reminder",
            description="Delete a reminder permanently. HIGH RISK: Requires explicit confirmation challenge token.",
            friendly_name="Deleting reminder",
            risk_level=RiskLevel.HIGH_RISK_WRITE,
            target_id_param="reminder_id",
            func=execute_delete_reminder,
            parameters_schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Unique reminder ID"},
                },
                "required": ["reminder_id"],
            },
        )
    )
