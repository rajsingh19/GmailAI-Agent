"""
Regression tests for WhatsApp stale-status and error-classification fixes.

Tests (T11-T20):
    T11  Successful test send: dest.status reset to 'enabled', last_error cleared.
    T12  Successful test send: previous delivery_issue status does not persist.
    T13  Previous 63016 last_error does not persist after successful send.
    T14  Body-only Sandbox payload contains no ContentSid.
    T15  Body-only Sandbox payload contains no ContentVariables.
    T16  Error 21654 classified as ContentSid/ContentVariables config error (not session expiry).
    T17  Error 63016 classified as outside-window (session expired) error.
    T18  Error 63007 classified as not-joined error.
    T19  Test API response includes error_code=None on success.
    T20  Failed test does NOT clear last_error or reset status to enabled.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
import httpx

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import SecurityManager
from app.core.phone import mask_phone_number
from app.models.user import User
from app.models.whatsapp_destination import WhatsAppDestination
from app.services.whatsapp.base import WhatsAppDeliveryResult
from app.services.whatsapp.message_builder import build_test_whatsapp_message
from app.services.whatsapp.twilio_provider import TwilioWhatsAppProvider
from app.services.whatsapp_service import WhatsAppService


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

async def _make_dest(db: AsyncSession, user_id: str, phone: str, *, status: str = "enabled") -> WhatsAppDestination:
    from app.core.security import SecurityManager
    from app.core.phone import mask_phone_number
    dest = WhatsAppDestination(
        user_id=user_id,
        phone_number_encrypted=SecurityManager.encrypt_token(phone),
        phone_number_masked=mask_phone_number(phone),
        enabled=True,
        opt_in_confirmed=True,
        opt_in_confirmed_at=datetime.now(timezone.utc),
        status=status,
        last_error="Your WhatsApp Sandbox session has expired (24-hour window)." if status == "delivery_issue" else None,
    )
    db.add(dest)
    await db.commit()
    await db.refresh(dest)
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# T11: Successful test send: dest.status reset to 'enabled', last_error cleared
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t11_success_clears_last_error_and_resets_status(
    test_db: AsyncSession,
    test_user: User,
):
    """After a successful test send, dest.status='enabled' and last_error=None."""
    dest = await _make_dest(test_db, test_user.id, "+919876595952", status="delivery_issue")
    assert dest.status == "delivery_issue"
    assert dest.last_error is not None

    with patch("app.services.whatsapp_service.get_whatsapp_provider") as mock_get, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_provider = AsyncMock()
        mock_provider.send_message.return_value = WhatsAppDeliveryResult(
            success=True, status="queued", message_sid="SMt11success"
        )
        mock_get.return_value = mock_provider

        result = await WhatsAppService.send_test_notification(db=test_db, user_id=test_user.id)

    assert result["success"] is True
    assert result["message_sid"] == "SMt11success"

    await test_db.refresh(dest)
    assert dest.status == "enabled", f"Expected 'enabled' after success, got '{dest.status}'"
    assert dest.last_error is None, f"Expected last_error=None after success, got '{dest.last_error}'"


# ─────────────────────────────────────────────────────────────────────────────
# T12: Previous delivery_issue status does not persist after successful send
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t12_delivery_issue_status_cleared_on_success(
    async_client: AsyncClient,
    test_db: AsyncSession,
    test_user: User,
):
    """GET /status after successful test must return status=enabled, not delivery_issue."""
    await _make_dest(test_db, test_user.id, "+919876595952", status="delivery_issue")
    token = SecurityManager.create_session_token(test_user.id)

    with patch("app.services.whatsapp_service.get_whatsapp_provider") as mock_get, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_provider = AsyncMock()
        mock_provider.send_message.return_value = WhatsAppDeliveryResult(
            success=True, status="queued", message_sid="SMt12"
        )
        mock_get.return_value = mock_provider

        res = await async_client.post(
            "/api/v1/notifications/whatsapp/test",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    # Now check the status endpoint
    status_res = await async_client.get(
        "/api/v1/notifications/whatsapp/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "enabled", (
        f"Expected status='enabled' after successful send, got '{status_data['status']}'"
    )
    assert status_data["last_error"] is None, (
        f"Expected last_error=None after successful send, got '{status_data['last_error']}'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T13: Previous 63016 error in last_error does not persist after successful send
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t13_previous_63016_error_cleared_on_success(
    test_db: AsyncSession,
    test_user: User,
):
    """A previous 63016 'session expired' last_error is cleared after a successful test."""
    dest = await _make_dest(test_db, test_user.id, "+919876595952", status="delivery_issue")
    # Manually set a 63016-style error
    dest.last_error = "Your WhatsApp Sandbox session has expired (24-hour window)."
    await test_db.commit()

    with patch("app.services.whatsapp_service.get_whatsapp_provider") as mock_get, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_provider = AsyncMock()
        mock_provider.send_message.return_value = WhatsAppDeliveryResult(
            success=True, status="queued", message_sid="SMt13"
        )
        mock_get.return_value = mock_provider

        result = await WhatsAppService.send_test_notification(db=test_db, user_id=test_user.id)

    assert result["success"] is True
    await test_db.refresh(dest)

    # Old 63016 error must be gone
    assert dest.last_error is None
    assert dest.status == "enabled"
    assert "expired" not in (dest.last_error or "")


# ─────────────────────────────────────────────────────────────────────────────
# T14: Body-only Sandbox payload contains no ContentSid
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t14_sandbox_body_only_no_contentsid():
    """Sandbox mode must never include ContentSid in the Twilio request payload."""
    provider = TwilioWhatsAppProvider(
        account_sid="ACtest1234",
        auth_token="authtest",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        json={"sid": "SMt14", "status": "queued"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        body, vars_ = build_test_whatsapp_message()
        await provider.send_message(
            to_phone="+919876595952",
            message=body,
            template_name="test",
            template_variables=vars_,
        )

    call_data = mock_post.call_args[1]["data"]
    assert "ContentSid" not in call_data, f"ContentSid must not be present in sandbox payload: {call_data}"
    assert "Body" in call_data


# ─────────────────────────────────────────────────────────────────────────────
# T15: Body-only Sandbox payload contains no ContentVariables
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t15_sandbox_body_only_no_contentvariables():
    """Sandbox mode must never include ContentVariables in the Twilio request payload."""
    provider = TwilioWhatsAppProvider(
        account_sid="ACtest1234",
        auth_token="authtest",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        json={"sid": "SMt15", "status": "queued"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        body, vars_ = build_test_whatsapp_message()
        await provider.send_message(
            to_phone="+919876595952",
            message=body,
            template_name="test",
            template_variables=vars_,
        )

    call_data = mock_post.call_args[1]["data"]
    assert "ContentVariables" not in call_data, (
        f"ContentVariables must not be present in sandbox payload: {call_data}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T16: Error 21654 classified as ContentSid/ContentVariables config error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t16_error_21654_classified_as_contentsid_config_error():
    """Twilio error 21654 must produce a ContentSid/ContentVariables error message,
    NOT a session/window expiry message."""
    provider = TwilioWhatsAppProvider(
        account_sid="ACtest1234",
        auth_token="authtest",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=400,
        headers={"content-type": "application/json"},
        json={"code": 21654, "message": "ContentSid Required", "status": 400},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await provider.send_message(
            to_phone="+919876595952",
            message="Test",
            template_name="test",
        )

    assert result.success is False
    assert result.error_code == "21654"

    # Must NOT say "session expired" or "24-hour"
    assert "expired" not in result.error_message.lower(), (
        f"21654 must not mention 'expired': {result.error_message}"
    )
    assert "24-hour" not in result.error_message.lower(), (
        f"21654 must not mention '24-hour': {result.error_message}"
    )

    # Must mention ContentSid or ContentVariables
    msg_lower = result.error_message.lower()
    assert "contentsid" in msg_lower or "contentvariables" in msg_lower, (
        f"21654 message should mention ContentSid/ContentVariables: {result.error_message}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T17: Error 63016 classified as outside-window (session expired) error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t17_error_63016_classified_as_session_expired():
    """Twilio error 63016 must produce a 'session expired / outside window' error message."""
    provider = TwilioWhatsAppProvider(
        account_sid="ACtest1234",
        auth_token="authtest",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=400,
        headers={"content-type": "application/json"},
        json={"code": 63016, "message": "Message outside window", "status": 400},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await provider.send_message(
            to_phone="+919876595952",
            message="Test",
            template_name="test",
        )

    assert result.success is False
    assert result.error_code == "63016"

    msg_lower = result.error_message.lower()
    assert "expired" in msg_lower or "24-hour" in msg_lower or "window" in msg_lower, (
        f"63016 message should mention session expiry/window: {result.error_message}"
    )
    # Must NOT mention ContentSid as the primary cause
    assert "contentsid" not in msg_lower or "join" in msg_lower, (
        f"63016 message should guide to rejoin, not mention ContentSid: {result.error_message}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T18: Error 63007 classified as not-joined error
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t18_error_63007_classified_as_not_joined():
    """Twilio error 63007 must produce a 'not joined / opt-in missing' error message."""
    provider = TwilioWhatsAppProvider(
        account_sid="ACtest1234",
        auth_token="authtest",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=400,
        headers={"content-type": "application/json"},
        json={"code": 63007, "message": "WhatsApp channel not enabled", "status": 400},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await provider.send_message(
            to_phone="+919876595952",
            message="Test",
            template_name="test",
        )

    assert result.success is False
    assert result.error_code == "63007"
    msg_lower = result.error_message.lower()
    assert "join" in msg_lower or "not joined" in msg_lower or "opt-in" in msg_lower, (
        f"63007 message should mention joining/opt-in: {result.error_message}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# T19: Successful test API response includes error_code=None
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t19_success_response_includes_error_code_none(
    test_db: AsyncSession,
    test_user: User,
):
    """Successful send_test_notification must return error_code=None explicitly."""
    await _make_dest(test_db, test_user.id, "+919876595952")

    with patch("app.services.whatsapp_service.get_whatsapp_provider") as mock_get, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_provider = AsyncMock()
        mock_provider.send_message.return_value = WhatsAppDeliveryResult(
            success=True, status="queued", message_sid="SMt19"
        )
        mock_get.return_value = mock_provider

        result = await WhatsAppService.send_test_notification(db=test_db, user_id=test_user.id)

    assert result["success"] is True
    assert "error_code" in result
    assert result["error_code"] is None


# ─────────────────────────────────────────────────────────────────────────────
# T20: Failed test does NOT clear last_error or reset status to enabled
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t20_failed_send_keeps_delivery_issue_status(
    test_db: AsyncSession,
    test_user: User,
):
    """A failed test send must keep status=delivery_issue and persist the error."""
    dest = await _make_dest(test_db, test_user.id, "+919876595952", status="enabled")

    with patch("app.services.whatsapp_service.get_whatsapp_provider") as mock_get, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_provider = AsyncMock()
        mock_provider.send_message.return_value = WhatsAppDeliveryResult(
            success=False,
            status="failed",
            error_code="63016",
            error_message="Your WhatsApp Sandbox session has expired.",
            is_transient=False,
        )
        mock_get.return_value = mock_provider

        result = await WhatsAppService.send_test_notification(db=test_db, user_id=test_user.id)

    assert result["success"] is False
    assert result["error_code"] == "63016"

    await test_db.refresh(dest)
    assert dest.status == "delivery_issue", f"Expected delivery_issue on failure, got '{dest.status}'"
    assert dest.last_error is not None
    assert "expired" in dest.last_error.lower() or "session" in dest.last_error.lower()
