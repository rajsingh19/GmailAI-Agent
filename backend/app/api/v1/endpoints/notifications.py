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
from app.schemas.push import (
    PushSubscriptionCreate,
    PushSubscriptionResponse,
    PushStatusResponse,
    PushUnsubscribeRequest,
    PushTestRequest,
    PushTestResponse,
)
from app.services.notification_service import NotificationService
from app.services.push_notification_service import PushNotificationService

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


# ==============================================================================
# Web Push Notification Endpoints
# ==============================================================================

@router.get("/push/vapid-public-key")
async def get_vapid_public_key(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the VAPID public application server key required for client-side PushManager subscription.
    Never exposes private key material.
    """
    key = PushNotificationService.get_vapid_public_key()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web Push notifications are not configured or enabled on the server.",
        )
    return {"vapid_public_key": key}


@router.get("/push/status", response_model=PushStatusResponse)
async def get_push_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the Web Push configuration status and all active registered devices for the current user.
    """
    return await PushNotificationService.get_user_push_status(db=db, user_id=current_user.id)


@router.post("/push/subscribe", response_model=PushSubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def subscribe_push_device(
    payload: PushSubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Registers or updates a Web Push subscription for the authenticated user's device.
    Strictly isolated: returns HTTP 409 Conflict if endpoint belongs to another account.
    """
    subscription = await PushNotificationService.subscribe_device(
        db=db,
        user_id=current_user.id,
        payload=payload,
    )
    return PushSubscriptionResponse.model_validate(subscription)


@router.delete("/push/unsubscribe")
async def unsubscribe_push_device(
    payload: PushUnsubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Unregisters a Web Push subscription endpoint owned by the authenticated user.
    """
    deleted = await PushNotificationService.unsubscribe_device(
        db=db,
        user_id=current_user.id,
        endpoint=payload.endpoint,
    )
    return {"unsubscribed": deleted}


@router.post("/push/test", response_model=PushTestResponse)
async def send_test_push_notification(
    payload: Optional[PushTestRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticated, rate-limited test endpoint to verify push notification delivery
    to the current user's registered devices.
    Never alters reminder states or accepts arbitrary user IDs.
    """
    req_payload = payload or PushTestRequest()
    test_data = {
        "title": req_payload.title or "Test Notification",
        "body": req_payload.body or "Web Push notifications are working properly!",
        "type": "test",
        "url": "/",
        "tag": "ai-assistant-test",
    }
    result = await PushNotificationService.send_notification_to_user(
        user_id=current_user.id,
        payload=test_data,
    )
    delivered = result.get("delivered", 0)
    failed = result.get("failed", 0)
    msg = (
        f"Delivered test notification to {delivered} device(s)."
        if delivered > 0
        else "No active device delivered. Ensure you have enabled notifications on this browser."
    )
    return PushTestResponse(
        status="success" if delivered > 0 else "no_devices",
        delivered_count=delivered,
        failed_count=failed,
        message=msg,
    )

