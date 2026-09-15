"""
Task Detector for Proactive AI Assistant (Milestone 8).
Detects overdue tasks, approaching deadlines (<=4h for high/urgent priority), and stale urgent tasks.
Operates strictly user-scoped with backend-controlled SuggestedAction models.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.schemas.proactive import SuggestedAction
from app.ai.agent.tool_registry import RiskLevel

logger = logging.getLogger(__name__)


class TaskDetector:
    """
    Scans active user tasks to generate proactive warnings for overdue items,
    approaching deadlines, and neglected high-priority responsibilities.
    """

    async def detect_tasks(
        self,
        db: AsyncSession,
        user_id: str,
        now_utc: Optional[datetime] = None,
    ) -> List[dict]:
        candidates: List[dict] = []
        now = now_utc or datetime.now(timezone.utc)

        # Query all active tasks for authenticated user
        stmt = (
            select(Task)
            .where(
                and_(
                    Task.user_id == user_id,
                    Task.status.in_(["pending", "in_progress"]),
                )
            )
            .order_by(Task.due_at.asc().nulls_last())
        )
        res = await db.execute(stmt)
        tasks = list(res.scalars().all())

        for task in tasks:
            # 1. Detection: Overdue Task (due_at < now)
            if task.due_at is not None:
                # Ensure task.due_at has timezone
                task_due = task.due_at
                if task_due.tzinfo is None:
                    task_due = task_due.replace(tzinfo=timezone.utc)

                if task_due < now:
                    time_overdue = now - task_due
                    hours_overdue = int(time_overdue.total_seconds() / 3600.0)
                    days_overdue = int(hours_overdue / 24)

                    if days_overdue > 0:
                        overdue_str = f"{days_overdue} day{'s' if days_overdue > 1 else ''} ago"
                    else:
                        overdue_str = f"{hours_overdue} hour{'s' if hours_overdue > 1 else ''} ago"

                    priority_level = "urgent" if task.priority in ["urgent", "high"] else "high"
                    day_anchor = task_due.strftime("%Y-%m-%d")

                    candidates.append({
                        "detection_type": "task_overdue",
                        "source_type": "task",
                        "source_id": task.id,
                        "title": f"Overdue Task: '{task.title}'",
                        "message": f"Task '{task.title}' was due {overdue_str} ({task_due.strftime('%b %d, %H:%M UTC')}). Would you like to complete or reschedule it?",
                        "priority": priority_level,
                        "idempotency_anchor": f"{day_anchor}_overdue",
                        "suggested_action": SuggestedAction(
                            action_type="complete_task",
                            target_resource="task",
                            target_id=task.id,
                            risk_level=RiskLevel.LOW_RISK_WRITE,
                            display_label=f"Mark '{task.title[:20]}' Complete",
                            action_payload={"task_id": task.id, "title": task.title},
                        ),
                        "metadata_json": {
                            "task_id": task.id,
                            "title": task.title,
                            "due_at": task_due.isoformat(),
                            "priority": task.priority,
                        },
                    })
                    continue

                # 2. Detection: Approaching Deadline (due within next 4 hours for high/urgent priority)
                diff_to_due = (task_due - now).total_seconds() / 3600.0
                if 0.0 <= diff_to_due <= 4.0 and task.priority in ["high", "urgent"]:
                    total_secs = max(0, int((task_due - now).total_seconds()))
                    hours_left = total_secs // 3600
                    mins_left = (total_secs % 3600) // 60
                    if hours_left > 0 and mins_left > 0:
                        time_left_str = f"{hours_left}h {mins_left}m"
                    elif hours_left > 0:
                        time_left_str = f"{hours_left}h 0m"
                    else:
                        time_left_str = f"{max(1, mins_left)} minutes"


                    candidates.append({
                        "detection_type": "task_due_soon",
                        "source_type": "task",
                        "source_id": task.id,
                        "title": f"Deadline in {time_left_str}: '{task.title}'",
                        "message": f"High priority task '{task.title}' is due in {time_left_str} ({task_due.strftime('%H:%M UTC')}).",
                        "priority": "high",
                        "idempotency_anchor": task_due.isoformat(),
                        "suggested_action": SuggestedAction(
                            action_type="complete_task",
                            target_resource="task",
                            target_id=task.id,
                            risk_level=RiskLevel.LOW_RISK_WRITE,
                            display_label=f"Mark '{task.title[:20]}' Complete",
                            action_payload={"task_id": task.id, "title": task.title},
                        ),
                        "metadata_json": {
                            "task_id": task.id,
                            "title": task.title,
                            "due_at": task_due.isoformat(),
                            "priority": task.priority,
                        },
                    })
                    continue

            # 3. Detection: Stale Urgent Task (created/updated > 7 days ago, priority == urgent, no due date)
            task_updated = task.updated_at
            if task_updated.tzinfo is None:
                task_updated = task_updated.replace(tzinfo=timezone.utc)

            if task.priority == "urgent" and (now - task_updated) > timedelta(days=7):
                updated_date_str = task_updated.strftime("%Y-%m-%d")
                candidates.append({
                    "detection_type": "stale_urgent_task",
                    "source_type": "task",
                    "source_id": task.id,
                    "title": f"Stale Urgent Task: '{task.title}'",
                    "message": f"Urgent task '{task.title}' has not been updated in over 7 days. Consider reviewing or updating status.",
                    "priority": "medium",
                    "idempotency_anchor": f"{updated_date_str}_stale",
                    "suggested_action": SuggestedAction(
                        action_type="complete_task",
                        target_resource="task",
                        target_id=task.id,
                        risk_level=RiskLevel.LOW_RISK_WRITE,
                        display_label=f"Mark '{task.title[:20]}' Complete",
                        action_payload={"task_id": task.id, "title": task.title},
                    ),
                    "metadata_json": {
                        "task_id": task.id,
                        "title": task.title,
                        "priority": task.priority,
                        "updated_at": task_updated.isoformat(),
                    },
                })

        return candidates
