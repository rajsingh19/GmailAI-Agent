import pytest
from unittest.mock import patch
from httpx import AsyncClient

from app.models.user import User
from app.core.config import settings
from app.core.security import SecurityManager
from app.services.push_notification_service import PushNotificationService


@pytest.mark.asyncio
async def test_get_vapid_public_key_unauthenticated(async_client: AsyncClient):
    """VAPID public key endpoint requires authentication."""
    resp = await async_client.get("/api/v1/notifications/push/vapid-public-key")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_vapid_public_key_authenticated(authenticated_client: AsyncClient):
    """Authenticated user can retrieve VAPID public key."""
    resp = await authenticated_client.get("/api/v1/notifications/push/vapid-public-key")
    assert resp.status_code == 200
    data = resp.json()
    assert "vapid_public_key" in data
    assert len(data["vapid_public_key"]) > 0


@pytest.mark.asyncio
async def test_push_subscribe_and_status(authenticated_client: AsyncClient):
    """Test subscribing a device and reading updated push status."""
    payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-device-endpoint-1",
        "keys": {
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9Q0v4IfRCoDEr00",
            "auth": "tBHItJI5svbpez7KI4CCXg",
        },
        "user_agent": "Mozilla/5.0 Chrome/120.0",
    }

    sub_resp = await authenticated_client.post(
        "/api/v1/notifications/push/subscribe",
        json=payload,
    )
    assert sub_resp.status_code == 201
    assert "id" in sub_resp.json()

    status_resp = await authenticated_client.get("/api/v1/notifications/push/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["enabled"] is True
    assert status_data["active_subscriptions"] == 1
    assert len(status_data["devices"]) == 1


@pytest.mark.asyncio
async def test_push_subscribe_cross_user_conflict(
    authenticated_client: AsyncClient,
    async_client: AsyncClient,
    test_user_b: User,
):
    """Test that User B attempting to subscribe User A's endpoint receives HTTP 409 Conflict."""
    endpoint = "https://fcm.googleapis.com/fcm/send/shared-conflict-device"
    payload_a = {
        "endpoint": endpoint,
        "keys": {
            "p256dh": "p256dh_a",
            "auth": "auth_a",
        },
        "user_agent": "User A Device",
    }

    # User A subscribes
    resp_a = await authenticated_client.post(
        "/api/v1/notifications/push/subscribe",
        json=payload_a,
    )
    assert resp_a.status_code == 201

    # User B logs in and attempts to subscribe with the exact same endpoint
    token_b = SecurityManager.create_session_token(test_user_b.id)
    resp_b = await async_client.post(
        "/api/v1/notifications/push/subscribe",
        json={
            "endpoint": endpoint,
            "keys": {
                "p256dh": "p256dh_b",
                "auth": "auth_b",
            },
            "user_agent": "User B Device",
        },
        cookies={settings.SESSION_COOKIE_NAME: token_b},
    )
    assert resp_b.status_code == 409
    assert "registered to another account" in resp_b.json()["detail"]


@pytest.mark.asyncio
async def test_push_test_endpoint(authenticated_client: AsyncClient):
    """Test the /push/test endpoint with mocked pywebpush."""
    # First subscribe a device
    await authenticated_client.post(
        "/api/v1/notifications/push/subscribe",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-endpoint-2",
            "keys": {
                "p256dh": "p256dh_2",
                "auth": "auth_2",
            },
        },
    )

    with patch.object(
        PushNotificationService,
        "send_notification_to_user",
        return_value={"delivered": 1, "failed": 0, "removed": 0, "purged": 0, "total": 1},
    ):
        test_resp = await authenticated_client.post(
            "/api/v1/notifications/push/test",
            json={"title": "Custom Test", "body": "Custom Body"},
        )
        assert test_resp.status_code == 200
        data = test_resp.json()
        assert data["status"] == "success"
        assert data["delivered_count"] == 1
