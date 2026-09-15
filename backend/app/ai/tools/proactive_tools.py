"""
Proactive Assistant AI Agent Tools (Milestone 8).
Provides read-only proactive context and notifications to the LLM.
"""
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolRegistry, ToolDefinition, RiskLevel
from app.models.notification import Notification
from app.models.user_preference import UserPreference

logger = logging.getLogger(__name__)


async def execute_get_proactive_notifications(
    user_id: str,
    db: AsyncSession,
    limit: int = 10,
    status_filter: Optional[str] = "unread",
) -> Dict[str, Any]:
    """
    Tool function for AI Agent to inspect recent proactive alerts and suggested actions.
    Strictly isolated to user_id. Returns untrusted context with backend citations.
    """
    try:
        base_query = select(Notification).where(
            and_(
                Notification.user_id == user_id,
                Notification.notification_type != "reminder",
            )
        )
        if status_filter:
            base_query = base_query.where(Notification.status == status_filter)

        stmt = base_query.order_by(Notification.created_at.desc()).limit(min(20, max(1, limit)))
        res = await db.execute(stmt)
        items = list(res.scalars().all())

        alerts = []
        for notif in items:
            meta = notif.metadata_json or {}
            alerts.append({
                "notification_id": notif.id,
                "type": notif.notification_type,
                "priority": notif.priority,
                "source": notif.source_type,
                "title": notif.title,
                "message": notif.message,
                "status": notif.status,
                "suggested_action": meta.get("suggested_action"),
                "citations": meta.get("citations", []),
                "created_at": notif.created_at.isoformat(),
            })

        return {
            "status": "success",
            "total_found": len(alerts),
            "alerts": alerts,
            "trusted": False,
        }
    except Exception as exc:
        logger.exception(f"Error executing get_proactive_notifications for user_id={user_id[:8]}: {exc}")
        return {
            "status": "error",
            "message": f"Failed to retrieve proactive notifications: {str(exc)}",
            "total_found": 0,
            "alerts": [],
            "trusted": False,
        }


def register_proactive_tools() -> None:
    """Registers proactive assistant read-only tools into the static ToolRegistry."""
    ToolRegistry.register(
        ToolDefinition(
            name="get_proactive_notifications",
            friendly_name="Get Proactive Notifications",
            description="Fetches recent proactive notifications, alerts, schedule conflicts, and suggested actions for the user.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of proactive alerts to return (default 10, max 20)",
                    },
                    "status_filter": {
                        "type": "string",
                        "description": "Filter by notification status: 'unread', 'read', 'dismissed', 'snoozed', or null for all",
                    },
                },
            },
            risk_level=RiskLevel.READ,
            func=execute_get_proactive_notifications,
        )
    )
