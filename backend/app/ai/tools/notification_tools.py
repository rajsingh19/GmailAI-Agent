from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolDefinition, ToolRegistry, RiskLevel
from app.services.notification_service import NotificationService


async def execute_list_notifications(
    user_id: str,
    db: AsyncSession,
    status: Optional[str] = None,
    limit: Optional[int] = 10,
) -> Dict[str, Any]:
    """Tool function to list in-app notifications for the authenticated user."""
    lim = min(max(limit or 10, 1), 20)
    items, total, unread_count = await NotificationService.list_notifications(
        db=db, user_id=user_id, status=status, limit=lim, offset=0
    )
    notifs = [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "status": n.status,
            "created_at": n.created_at.isoformat(),
        }
        for n in items
    ]
    return {
        "status": "success",
        "total": total,
        "unread_count": unread_count,
        "notifications": notifs,
    }


async def execute_mark_notification_read(
    user_id: str,
    db: AsyncSession,
    notification_id: str,
) -> Dict[str, Any]:
    """Tool function to mark a single notification as read."""
    marked = await NotificationService.mark_as_read(db=db, user_id=user_id, notification_ids=[notification_id])
    if marked == 0:
        return {"status": "error", "message": f"Notification '{notification_id}' not found or already read."}

    return {
        "status": "success",
        "message": "Notification marked as read.",
        "notification_id": notification_id,
    }


async def execute_mark_all_notifications_read(
    user_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Tool function to mark all unread notifications as read."""
    count = await NotificationService.mark_as_read(db=db, user_id=user_id, notification_ids=None)
    return {
        "status": "success",
        "message": f"Marked {count} notifications as read.",
        "marked_count": count,
    }


def register_notification_tools() -> None:
    """Registers notification tools into ToolRegistry."""
    ToolRegistry.register(
        ToolDefinition(
            name="list_notifications",
            description="List user in-app notifications and unread alert counts.",
            friendly_name="Listing alerts",
            risk_level=RiskLevel.READ,
            func=execute_list_notifications,
            parameters_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["unread", "read"], "description": "Filter by read status"},
                    "limit": {"type": "integer", "description": "Max notifications to return (default 10, max 20)"},
                },
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="mark_notification_read",
            description="Mark a specific notification as read.",
            friendly_name="Marking alert as read",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_mark_notification_read,
            parameters_schema={
                "type": "object",
                "properties": {
                    "notification_id": {"type": "string", "description": "ID of the notification to mark read"},
                },
                "required": ["notification_id"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="mark_all_notifications_read",
            description="Mark all unread in-app notifications as read.",
            friendly_name="Marking all alerts read",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_mark_all_notifications_read,
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )
    )
