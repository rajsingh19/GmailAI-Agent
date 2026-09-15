"""
Reminder Detector for Proactive AI Assistant (Milestone 8).
Detects repeatedly snoozed reminders (>= 3 times) and missed recurring reminder schedules.
Does NOT duplicate M5 reminder execution.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder
from app.schemas.proactive import SuggestedAction
from app.ai.agent.tool_registry import RiskLevel

logger = logging.getLogger(__name__)


class ReminderDetector:
    """
    Scans active reminders to detect problematic patterns like repeated snoozing,
    prompting the user to reschedule or resolve them.
    """

    async def detect_reminders(
        self,
        db: AsyncSession,
        user_id: str,
        now_utc: Optional[datetime] = None,
    ) -> List[dict]:
        candidates: List[dict] = []
        now = now_utc or datetime.now(timezone.utc)

        stmt = (
            select(Reminder)
            .where(
                and_(
                    Reminder.user_id == user_id,
                    Reminder.status.in_(["scheduled", "snoozed"]),
                )
            )
        )
        res = await db.execute(stmt)
        reminders = list(res.scalars().all())

        for reminder in reminders:
            # 1. Detection: Repeated Snoozing (retry_count >= 3)
            if reminder.retry_count >= 3 and reminder.status == "snoozed":
                candidates.append({
                    "detection_type": "repeated_snoozing",
                    "source_type": "reminder",
                    "source_id": reminder.id,
                    "title": f"Repeatedly Snoozed Reminder: '{reminder.title}'",
                    "message": f"Reminder '{reminder.title}' has been snoozed {reminder.retry_count} times. Would you like to reschedule or complete it?",
                    "priority": "medium",
                    "idempotency_anchor": f"snooze_{reminder.retry_count}",
                    "suggested_action": SuggestedAction(
                        action_type="snooze_reminder",
                        target_resource="reminder",
                        target_id=reminder.id,
                        risk_level=RiskLevel.LOW_RISK_WRITE,
                        display_label=f"Reschedule '{reminder.title[:20]}'",
                        action_payload={"reminder_id": reminder.id, "duration": "1d"},
                    ),
                    "metadata_json": {
                        "reminder_id": reminder.id,
                        "title": reminder.title,
                        "retry_count": reminder.retry_count,
                        "remind_at": reminder.remind_at.isoformat() if reminder.remind_at else None,
                    },
                })

            # 2. Detection: Missed / Overdue Recurring Reminder
            rem_time = reminder.next_trigger_at or reminder.remind_at
            if rem_time is not None:
                if rem_time.tzinfo is None:
                    rem_time = rem_time.replace(tzinfo=timezone.utc)

                if reminder.recurrence_rule and rem_time < (now - timedelta(hours=24)) and reminder.status == "scheduled":
                    candidates.append({
                        "detection_type": "missed_recurring",
                        "source_type": "reminder",
                        "source_id": reminder.id,
                        "title": f"Overdue Recurring Reminder: '{reminder.title}'",
                        "message": f"Recurring reminder '{reminder.title}' scheduled for {rem_time.strftime('%b %d')} has not triggered or been acknowledged.",
                        "priority": "high",
                        "idempotency_anchor": rem_time.strftime("%Y-%m-%d"),
                        "suggested_action": SuggestedAction(
                            action_type="snooze_reminder",
                            target_resource="reminder",
                            target_id=reminder.id,
                            risk_level=RiskLevel.LOW_RISK_WRITE,
                            display_label=f"Acknowledge '{reminder.title[:20]}'",
                            action_payload={"reminder_id": reminder.id, "duration": "1h"},
                        ),
                        "metadata_json": {
                            "reminder_id": reminder.id,
                            "title": reminder.title,
                            "remind_at": rem_time.isoformat(),
                        },
                    })

        return candidates
