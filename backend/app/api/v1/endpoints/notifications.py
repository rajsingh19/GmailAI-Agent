from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationMarkReadRequest,
)
from app.services.notification_service import NotificationService

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    status: Optional[str] = Query(None, description="Filter by status: unread, read"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List in-app notifications for the authenticated user."""
    items, total, unread_count = await NotificationService.list_notifications(
        db=db,
        user_id=current_user.id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return NotificationListResponse(items=items, total=total, unread_count=unread_count)


@router.post("/read")
async def mark_notifications_read(
    body: Optional[NotificationMarkReadRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark specific notifications or all unread notifications as read."""
    notification_ids = body.notification_ids if body else None
    count = await NotificationService.mark_as_read(
        db=db,
        user_id=current_user.id,
        notification_ids=notification_ids,
    )
    return {"marked_read_count": count}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a notification owned by the authenticated user."""
    deleted = await NotificationService.delete_notification(
        db=db, user_id=current_user.id, notification_id=notification_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification with ID '{notification_id}' not found",
        )
    return None
