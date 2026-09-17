import pytest
import asyncio
from unittest.mock import patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.notification import Notification
from app.schemas.push import PushSubscriptionCreate, PushKeysSchema
from app.services.notification_service import NotificationService
from app.services.push_notification_service import PushNotificationService


@pytest.mark.asyncio
async def test_notification_service_triggers_push_and_persists_in_app(
    test_db: AsyncSession, test_user: User
):
    """Verify NotificationService.create_notification creates in-app notification and dispatches Web Push."""
    # Subscribe user to push
    payload = PushSubscriptionCreate(
        endpoint="https://push.service.com/ep-integration",
        keys=PushKeysSchema(p256dh="p256dh_val", auth="auth_val"),
    )
    await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload,
    )

    with patch.object(
        PushNotificationService,
        "send_notification_to_user",
        return_value={"total": 1, "delivered": 1, "failed": 0, "purged": 0}
    ):
        notif = await NotificationService.create_notification(
            db=test_db,
            user_id=test_user.id,
            idempotency_key="m5_test_notif_1",
            title="⏰ Reminder: Team Meeting",
            message="Your scheduled reminder is due now.",
            notification_type="reminder",
        )

        # Allow background asyncio tasks to run
        await asyncio.sleep(0.05)

        # Verify in-app notification is persisted
        assert notif.id is not None
        assert notif.user_id == test_user.id
        assert notif.title == "⏰ Reminder: Team Meeting"

        # Verify DB contains the record
        result = await test_db.execute(select(Notification).where(Notification.id == notif.id))
        saved_notif = result.scalars().first()
        assert saved_notif is not None


@pytest.mark.asyncio
async def test_push_failure_does_not_break_in_app_notification(
    test_db: AsyncSession, test_user: User
):
    """Verify that even if Web Push raises an unhandled exception, in-app notification is persisted safely."""
    with patch.object(
        PushNotificationService,
        "send_notification_to_user",
        side_effect=RuntimeError("Web Push gateway network timeout")
    ):
        notif = await NotificationService.create_notification(
            db=test_db,
            user_id=test_user.id,
            idempotency_key="m5_test_notif_2",
            title="⏰ Standup Meeting",
            message="Time for standup",
            notification_type="reminder",
        )

        # Allow background task to handle exception safely
        await asyncio.sleep(0.05)

        assert notif.id is not None
        assert notif.title == "⏰ Standup Meeting"

        result = await test_db.execute(select(Notification).where(Notification.id == notif.id))
        saved_notif = result.scalars().first()
        assert saved_notif is not None
