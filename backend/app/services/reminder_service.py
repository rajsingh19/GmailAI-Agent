from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
import zoneinfo
from dateutil import rrule
from sqlalchemy import select, func, desc, nullslast
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder
from app.models.task import Task
from app.schemas.reminder import ReminderCreate, ReminderUpdate, ReminderSnooze


def compute_next_occurrence(
    recurrence_rule: str,
    base_dt: datetime,
    after_dt: datetime,
    tz_name: str = "UTC",
) -> Optional[datetime]:
    """
    Computes the next occurrence timestamp after `after_dt` based on RFC 5545 RRULE.
    Handles timezone wall-clock time and DST transitions safely.
    Returns UTC timezone-aware datetime or None if no more occurrences.
    """
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    # Convert base_dt and after_dt to target local timezone
    if base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=timezone.utc)
    if after_dt.tzinfo is None:
        after_dt = after_dt.replace(tzinfo=timezone.utc)

    local_base = base_dt.astimezone(tz)
    local_after = after_dt.astimezone(tz)

    # Clean rrule string
    rule_str = recurrence_rule.strip()
    if not rule_str.upper().startswith("RRULE:"):
        rule_str = f"RRULE:{rule_str}"

    # Use naive representations in the local timezone for dateutil.rrule to preserve wall-clock time across DST
    naive_base = local_base.replace(tzinfo=None)
    naive_after = local_after.replace(tzinfo=None)

    rule = rrule.rrulestr(rule_str, dtstart=naive_base)
    next_naive = rule.after(naive_after, inc=False)

    if not next_naive:
        return None

    # Re-attach local timezone and convert to UTC
    next_local = next_naive.replace(tzinfo=tz)
    return next_local.astimezone(timezone.utc)


def parse_snooze_duration(duration: str, from_dt: datetime) -> datetime:
    """Parse snooze duration string into a future datetime."""
    durations = {
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
    }
    delta = durations.get(duration)
    if not delta:
        raise ValueError(f"Unsupported snooze duration: {duration}. Supported: 5m, 15m, 30m, 1h, 1d")
    return from_dt + delta


class ReminderService:
    """
    Reminder management service.
    Enforces user isolation, task ownership validation, DST safety, and state machine integrity.
    """

    @staticmethod
    async def create_reminder(
        db: AsyncSession, user_id: str, reminder_in: ReminderCreate
    ) -> Reminder:
        """Create a new reminder for the user."""
        # If task_id provided, validate task ownership
        if reminder_in.task_id:
            task_stmt = select(Task).where(Task.id == reminder_in.task_id, Task.user_id == user_id)
            task_res = await db.execute(task_stmt)
            if not task_res.scalar_one_or_none():
                raise ValueError(f"Task with ID {reminder_in.task_id} not found or does not belong to user")

        # Ensure remind_at is converted to UTC for initial next_trigger_at
        utc_remind_at = reminder_in.remind_at.astimezone(timezone.utc)

        reminder = Reminder(
            user_id=user_id,
            task_id=reminder_in.task_id,
            title=reminder_in.title,
            message=reminder_in.message,
            remind_at=reminder_in.remind_at,
            timezone=reminder_in.timezone or "UTC",
            recurrence_rule=reminder_in.recurrence_rule,
            status="scheduled",
            next_trigger_at=utc_remind_at,
            retry_count=0,
        )
        db.add(reminder)
        await db.commit()
        await db.refresh(reminder)
        return reminder

    @staticmethod
    async def get_reminder(
        db: AsyncSession, user_id: str, reminder_id: str
    ) -> Optional[Reminder]:
        """Get a reminder by ID scoped to user_id."""
        stmt = select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_reminders(
        db: AsyncSession,
        user_id: str,
        status: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Reminder], int]:
        """List reminders for user with optional status/task filtering."""
        base_query = select(Reminder).where(Reminder.user_id == user_id)
        count_query = select(func.count()).select_from(Reminder).where(Reminder.user_id == user_id)

        if status:
            base_query = base_query.where(Reminder.status == status)
            count_query = count_query.where(Reminder.status == status)
        if task_id:
            base_query = base_query.where(Reminder.task_id == task_id)
            count_query = count_query.where(Reminder.task_id == task_id)

        total_res = await db.execute(count_query)
        total = total_res.scalar_one() or 0

        stmt = (
            base_query.order_by(
                nullslast(Reminder.next_trigger_at.asc()),
                desc(Reminder.created_at),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await db.execute(stmt)
        items = list(res.scalars().all())
        return items, total

    @staticmethod
    async def update_reminder(
        db: AsyncSession, user_id: str, reminder_id: str, reminder_in: ReminderUpdate
    ) -> Optional[Reminder]:
        """Update an existing reminder owned by the user."""
        reminder = await ReminderService.get_reminder(db, user_id=user_id, reminder_id=reminder_id)
        if not reminder:
            return None

        update_data = reminder_in.model_dump(exclude_unset=True)

        if "task_id" in update_data and update_data["task_id"] is not None:
            task_stmt = select(Task).where(Task.id == update_data["task_id"], Task.user_id == user_id)
            task_res = await db.execute(task_stmt)
            if not task_res.scalar_one_or_none():
                raise ValueError(f"Task with ID {update_data['task_id']} not found or does not belong to user")

        if "remind_at" in update_data and update_data["remind_at"] is not None:
            new_remind_at = update_data["remind_at"]
            if reminder.status in ("scheduled", "snoozed"):
                reminder.next_trigger_at = new_remind_at.astimezone(timezone.utc)

        for field, val in update_data.items():
            setattr(reminder, field, val)

        await db.commit()
        await db.refresh(reminder)
        return reminder

    @staticmethod
    async def snooze_reminder(
        db: AsyncSession, user_id: str, reminder_id: str, snooze_in: ReminderSnooze
    ) -> Optional[Reminder]:
        """Snooze a reminder to a future time."""
        reminder = await ReminderService.get_reminder(db, user_id=user_id, reminder_id=reminder_id)
        if not reminder:
            return None

        if reminder.status in ("cancelled", "failed"):
            raise ValueError(f"Cannot snooze reminder with status '{reminder.status}'")

        now_utc = datetime.now(timezone.utc)
        if snooze_in.snooze_until:
            snooze_dt = snooze_in.snooze_until.astimezone(timezone.utc)
        elif snooze_in.duration:
            snooze_dt = parse_snooze_duration(snooze_in.duration, now_utc)
        else:
            raise ValueError("Must provide either 'duration' or 'snooze_until'")

        if snooze_dt <= now_utc:
            raise ValueError("Snooze time must be in the future")

        reminder.snoozed_until = snooze_dt
        reminder.next_trigger_at = snooze_dt
        reminder.status = "snoozed"
        await db.commit()
        await db.refresh(reminder)
        return reminder

    @staticmethod
    async def cancel_reminder(
        db: AsyncSession, user_id: str, reminder_id: str
    ) -> Optional[Reminder]:
        """Cancel a reminder so it will never execute again."""
        reminder = await ReminderService.get_reminder(db, user_id=user_id, reminder_id=reminder_id)
        if not reminder:
            return None

        reminder.status = "cancelled"
        reminder.next_trigger_at = None
        reminder.snoozed_until = None
        await db.commit()
        await db.refresh(reminder)
        return reminder

    @staticmethod
    async def delete_reminder(
        db: AsyncSession, user_id: str, reminder_id: str
    ) -> bool:
        """Delete a reminder owned by the user."""
        reminder = await ReminderService.get_reminder(db, user_id=user_id, reminder_id=reminder_id)
        if not reminder:
            return False

        await db.delete(reminder)
        await db.commit()
        return True
