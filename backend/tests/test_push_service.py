import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pywebpush import WebPushException

from app.models.user import User
from app.schemas.push import PushSubscriptionCreate, PushKeysSchema
from app.services.push_notification_service import PushNotificationService


@pytest.mark.asyncio
async def test_subscribe_device_success(test_db: AsyncSession, test_user: User):
    """Test subscribing a new device for a user."""
    payload = PushSubscriptionCreate(
        endpoint="https://push.service.com/ep1",
        keys=PushKeysSchema(p256dh="p256dh_val_1", auth="auth_val_1"),
        user_agent="Firefox/Linux",
    )
    sub = await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload,
    )

    assert sub.id is not None
    assert sub.user_id == test_user.id
    assert sub.endpoint == "https://push.service.com/ep1"
    assert sub.user_agent == "Firefox/Linux"


@pytest.mark.asyncio
async def test_subscribe_device_cross_user_conflict_409(
    test_db: AsyncSession, test_user: User, test_user_b: User
):
    """Test that User B cannot subscribe to User A's endpoint, triggering HTTP 409 Conflict."""
    endpoint = "https://push.service.com/ep-shared"

    # User A subscribes
    payload_a = PushSubscriptionCreate(
        endpoint=endpoint,
        keys=PushKeysSchema(p256dh="p256dh_a", auth="auth_a"),
    )
    await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload_a,
    )

    # User B tries to claim same endpoint
    payload_b = PushSubscriptionCreate(
        endpoint=endpoint,
        keys=PushKeysSchema(p256dh="p256dh_b", auth="auth_b"),
    )
    with pytest.raises(HTTPException) as exc_info:
        await PushNotificationService.subscribe_device(
            db=test_db,
            user_id=test_user_b.id,
            payload=payload_b,
        )
    assert exc_info.value.status_code == 409
    assert "registered to another account" in exc_info.value.detail


@pytest.mark.asyncio
async def test_subscribe_device_same_user_update(test_db: AsyncSession, test_user: User):
    """Test that if the same user refreshes/re-subscribes their existing endpoint, keys are updated."""
    endpoint = "https://push.service.com/ep-update"

    # First subscribe
    payload_1 = PushSubscriptionCreate(
        endpoint=endpoint,
        keys=PushKeysSchema(p256dh="initial_key", auth="initial_auth"),
        user_agent="Browser 1.0",
    )
    sub1 = await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload_1,
    )
    initial_id = sub1.id

    # Re-subscribe same endpoint with updated keys
    payload_2 = PushSubscriptionCreate(
        endpoint=endpoint,
        keys=PushKeysSchema(p256dh="refreshed_key", auth="refreshed_auth"),
        user_agent="Browser 2.0",
    )
    sub2 = await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload_2,
    )

    assert sub2.id == initial_id
    assert sub2.p256dh_key == "refreshed_key"
    assert sub2.user_agent == "Browser 2.0"


@pytest.mark.asyncio
async def test_unsubscribe_device(test_db: AsyncSession, test_user: User):
    """Test unsubscribing an endpoint."""
    endpoint = "https://push.service.com/ep-unsub"

    payload = PushSubscriptionCreate(
        endpoint=endpoint,
        keys=PushKeysSchema(p256dh="key", auth="auth"),
    )
    await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload,
    )

    # Unsubscribe
    unsub_res = await PushNotificationService.unsubscribe_device(
        db=test_db, user_id=test_user.id, endpoint=endpoint
    )
    assert unsub_res is True

    # Unsubscribing again returns False cleanly
    unsub_again = await PushNotificationService.unsubscribe_device(
        db=test_db, user_id=test_user.id, endpoint=endpoint
    )
    assert unsub_again is False


@pytest.mark.asyncio
async def test_get_user_push_status(test_db: AsyncSession, test_user: User):
    """Test retrieving push status and device listing for a user."""
    payload = PushSubscriptionCreate(
        endpoint="https://push.service.com/ep-device-1",
        keys=PushKeysSchema(p256dh="k1", auth="a1"),
        user_agent="Chrome on Android",
    )
    await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload,
    )

    status = await PushNotificationService.get_user_push_status(db=test_db, user_id=test_user.id)
    assert status.enabled is True
    assert status.active_subscriptions == 1
    assert len(status.devices) == 1
    assert status.devices[0].user_agent == "Chrome on Android"


@pytest.mark.asyncio
async def test_send_notification_purges_410_gone(test_db: AsyncSession, test_user: User):
    """Test that HTTP 404/410 from push provider automatically purges the dead subscription."""
    payload = PushSubscriptionCreate(
        endpoint="https://push.service.com/ep-dead",
        keys=PushKeysSchema(p256dh="k_dead", auth="a_dead"),
    )
    await PushNotificationService.subscribe_device(
        db=test_db,
        user_id=test_user.id,
        payload=payload,
    )

    mock_response = MagicMock()
    mock_response.status_code = 410
    mock_exception = WebPushException("Subscription has expired or is invalid", response=mock_response)

    with patch("app.services.push_notification_service.webpush", side_effect=mock_exception):
        result = await PushNotificationService.send_notification_to_user(
            user_id=test_user.id,
            title="Test 410 Purge",
            body="This subscription should be purged",
            db=test_db,
        )

    assert result["purged"] == 1

    # Verify device is now purged from DB
    status = await PushNotificationService.get_user_push_status(db=test_db, user_id=test_user.id)
    assert status.active_subscriptions == 0
