"""
Regression tests for masked-phone-number bug and WhatsApp send-test-notification security.

Bug summary:
    The frontend was populating the phone input with the masked display value
    (e.g. '+91******5952') and submitting it back to the backend. The backend
    correctly rejected it, but the fix must be defence-in-depth:
      1. Backend rejects masked numbers at normalize_phone_number().
      2. Backend test endpoint uses only the encrypted DB record (no frontend phone accepted).
      3. Frontend never populates the input with a masked value (tested indirectly via API contract).

Tests (T1-T10):
    T1  Status API returns masked phone only — never the decrypted plain number.
    T2  Masked value cannot be used as a Twilio destination (validate_configuration path).
    T3  POST /whatsapp/test with empty body retrieves encrypted phone from authenticated user's DB record.
    T4  POST /whatsapp/test uses decrypted DB phone, not any frontend-supplied value.
    T5  Twilio provider receives real E.164, not the masked display value.
    T6  POST /whatsapp/test cannot target another user's phone number (user isolation).
    T7  Masked phone number is rejected by normalize_phone_number (backend guard).
    T8  Changing phone requires an explicit new E.164 — masked value is rejected.
    T9  Sandbox mode sends Body and no ContentSid.
    T10 Production mode without ContentSid is rejected locally.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
import httpx

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.phone import normalize_phone_number, mask_phone_number, InvalidPhoneNumberError
from app.core.security import SecurityManager
from app.models.user import User
from app.models.whatsapp_destination import WhatsAppDestination
from app.services.whatsapp.base import WhatsAppDeliveryResult
from app.services.whatsapp.message_builder import build_test_whatsapp_message
from app.services.whatsapp.twilio_provider import TwilioWhatsAppProvider
from app.services.whatsapp_service import WhatsAppService


# ─────────────────────────────────────────────────────────
# T1: Status API returns masked phone only
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t1_status_api_returns_masked_not_plain(
    async_client: AsyncClient,
    test_db: AsyncSession,
    test_user: User,
):
    """Status API must return phone_number_masked, never the decrypted E.164 number."""
    plain_phone = "+919876595952"
    encrypted = SecurityManager.encrypt_token(plain_phone)
    masked = mask_phone_number(plain_phone)

    dest = WhatsAppDestination(
        user_id=test_user.id,
        phone_number_encrypted=encrypted,
        phone_number_masked=masked,
        enabled=True,
        opt_in_confirmed=True,
        opt_in_confirmed_at=datetime.now(timezone.utc),
        status="enabled",
    )
    test_db.add(dest)
    await test_db.commit()

    token = SecurityManager.create_session_token(test_user.id)
    res = await async_client.get(
        "/api/v1/notifications/whatsapp/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()

    # Masked value must be present
    assert data["phone_number_masked"] == masked
    assert "*" in data["phone_number_masked"]

    # Plain phone must NEVER appear in the response body
    response_text = res.text
    assert plain_phone not in response_text, (
        f"Decrypted phone number '{plain_phone}' must never appear in the API response"
    )


# ─────────────────────────────────────────────────────────
# T2: Masked value cannot be used as Twilio destination
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t2_masked_value_rejected_by_twilio_provider():
    """Twilio provider must not be able to format a masked number as a valid WhatsApp destination."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    # Attempting to send with a masked number must fail at phone formatting/normalisation
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        result = await provider.send_message(
            to_phone="+91******5952",  # masked value
            message="Test",
        )

    assert result.success is False
    assert result.error_code in ("INVALID_PHONE", "CONFIG_ERROR")
    # Twilio API must NOT have been called
    mock_post.assert_not_called()


# ─────────────────────────────────────────────────────────
# T3: POST /whatsapp/test with empty body retrieves encrypted phone from DB
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t3_test_endpoint_no_body_uses_db_phone(
    async_client: AsyncClient,
    test_db: AsyncSession,
    test_user: User,
):
    """POST /whatsapp/test accepts NO phone number in the body. It uses the session user's DB record."""
    plain_phone = "+919876595952"
    dest = WhatsAppDestination(
        user_id=test_user.id,
        phone_number_encrypted=SecurityManager.encrypt_token(plain_phone),
        phone_number_masked=mask_phone_number(plain_phone),
        enabled=True,
        opt_in_confirmed=True,
        opt_in_confirmed_at=datetime.now(timezone.utc),
        status="enabled",
    )
    test_db.add(dest)
    await test_db.commit()

    token = SecurityManager.create_session_token(test_user.id)

    with patch("app.services.whatsapp.twilio_provider.TwilioWhatsAppProvider.send_message") as mock_send, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_send.return_value = WhatsAppDeliveryResult(
            success=True, status="queued", message_sid="SMtest_t3"
        )

        # POST with EMPTY body — no phone number supplied
        res = await async_client.post(
            "/api/v1/notifications/whatsapp/test",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["message_sid"] == "SMtest_t3"


# ─────────────────────────────────────────────────────────
# T4: POST /whatsapp/test uses decrypted DB phone, not any frontend value
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t4_test_endpoint_decrypts_and_uses_db_phone(
    test_db: AsyncSession,
    test_user: User,
):
    """WhatsAppService.send_test_notification must decrypt the DB phone and pass it to the provider."""
    plain_phone = "+919876595952"
    masked = mask_phone_number(plain_phone)

    dest = WhatsAppDestination(
        user_id=test_user.id,
        phone_number_encrypted=SecurityManager.encrypt_token(plain_phone),
        phone_number_masked=masked,
        enabled=True,
        opt_in_confirmed=True,
        opt_in_confirmed_at=datetime.now(timezone.utc),
        status="enabled",
    )
    test_db.add(dest)
    await test_db.commit()

    captured_calls = []

    async def fake_send(to_phone, message, template_name=None, template_variables=None, status_callback=None):
        captured_calls.append({"to_phone": to_phone, "message": message})
        return WhatsAppDeliveryResult(success=True, status="queued", message_sid="SMtest_t4")

    with patch("app.services.whatsapp_service.get_whatsapp_provider") as mock_get_provider, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_provider = AsyncMock()
        mock_provider.send_message.side_effect = fake_send
        mock_get_provider.return_value = mock_provider

        result = await WhatsAppService.send_test_notification(db=test_db, user_id=test_user.id)

    assert result["success"] is True
    assert len(captured_calls) == 1

    actual_to = captured_calls[0]["to_phone"]
    # Provider must receive the real decrypted number
    assert actual_to == plain_phone, f"Expected real E.164 '{plain_phone}', got '{actual_to}'"
    # Masked value must never be passed to Twilio
    assert masked not in actual_to
    assert "*" not in actual_to


# ─────────────────────────────────────────────────────────
# T5: Twilio provider receives real E.164, not masked value
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t5_twilio_provider_receives_real_e164_not_masked():
    """Twilio provider call data must contain the real E.164 number, not the masked display value."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        json={"sid": "SMreal_e164", "status": "queued"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        body, vars_ = build_test_whatsapp_message()
        result = await provider.send_message(
            to_phone="+919876595952",  # real E.164
            message=body,
            template_name="test",
        )

    assert result.success is True
    call_data = mock_post.call_args[1]["data"]

    # Verify destination is real E.164 format
    assert call_data["To"] == "whatsapp:+919876595952"
    assert "*" not in call_data["To"]

    # Body present (sandbox), no ContentSid
    assert call_data["Body"] == body
    assert "ContentSid" not in call_data


# ─────────────────────────────────────────────────────────
# T6: POST /whatsapp/test cannot target another user's phone
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t6_test_notification_user_isolation(
    async_client: AsyncClient,
    test_db: AsyncSession,
    test_user: User,
):
    """User A's test notification must only use User A's encrypted phone, never User B's."""
    # User A with a phone configured
    user_a = test_user
    phone_a = "+919876595952"
    dest_a = WhatsAppDestination(
        user_id=user_a.id,
        phone_number_encrypted=SecurityManager.encrypt_token(phone_a),
        phone_number_masked=mask_phone_number(phone_a),
        enabled=True,
        opt_in_confirmed=True,
        opt_in_confirmed_at=datetime.now(timezone.utc),
        status="enabled",
    )
    test_db.add(dest_a)

    # User B with a different phone
    user_b = User(
        id="usr_test_isolation_b",
        email="user_b_isolation@example.com",
        full_name="User B Isolation",
        is_active=True,
    )
    test_db.add(user_b)
    await test_db.commit()

    token_b = SecurityManager.create_session_token(user_b.id)

    with patch("app.services.whatsapp.twilio_provider.TwilioWhatsAppProvider.send_message") as mock_send, \
         patch("app.services.whatsapp_service.WhatsAppService.is_enabled", return_value=True):
        mock_send.return_value = WhatsAppDeliveryResult(success=True, status="queued", message_sid="SMisolation")

        # User B sends a test — must NOT reach User A's phone
        res = await async_client.post(
            "/api/v1/notifications/whatsapp/test",
            headers={"Authorization": f"Bearer {token_b}"},
        )

    assert res.status_code == 200
    data = res.json()
    # User B has no configured destination → must fail gracefully
    assert data["success"] is False
    assert data.get("status") in ("not_configured", "not_opted_in", "disabled")
    # Twilio must NOT have been called at all
    mock_send.assert_not_called()


# ─────────────────────────────────────────────────────────
# T7: normalize_phone_number rejects masked values
# ─────────────────────────────────────────────────────────

def test_t7_normalize_phone_rejects_masked_values():
    """normalize_phone_number must raise InvalidPhoneNumberError for any masked display value."""
    masked_inputs = [
        "+91******5952",
        "+1******2671",
        "+******1234",
        "+91****1234",
    ]
    for masked in masked_inputs:
        with pytest.raises(InvalidPhoneNumberError) as exc_info:
            normalize_phone_number(masked)
        assert "Masked phone numbers" in str(exc_info.value) or "display-only" in str(exc_info.value), \
            f"Expected masked-number rejection message, got: {exc_info.value}"


# ─────────────────────────────────────────────────────────
# T8: Changing phone requires explicit new E.164 — masked is rejected
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t8_configure_destination_rejects_masked_phone(
    async_client: AsyncClient,
    test_db: AsyncSession,
    test_user: User,
):
    """PUT /whatsapp/destination must reject a masked display value as the phone_number."""
    token = SecurityManager.create_session_token(test_user.id)

    res = await async_client.put(
        "/api/v1/notifications/whatsapp/destination",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "+91******5952", "opt_in": True},
    )

    assert res.status_code == 422, (
        f"Expected 422 Unprocessable Entity for masked phone input, got {res.status_code}: {res.text}"
    )
    assert "display-only" in res.text or "Masked" in res.text or "masked" in res.text


# ─────────────────────────────────────────────────────────
# T9: Sandbox mode uses Body, no ContentSid
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t9_sandbox_test_uses_body_no_contentsid():
    """Sandbox mode must send Body only; ContentSid must not appear in the Twilio payload."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        json={"sid": "SMsandbox_t9", "status": "queued"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        body, vars_ = build_test_whatsapp_message()
        result = await provider.send_message(
            to_phone="+919876595952",
            message=body,
            template_name="test",
            template_variables=vars_,
        )

    assert result.success is True
    data = mock_post.call_args[1]["data"]
    assert "Body" in data
    assert data["Body"] == "Your Personal AI Assistant WhatsApp notifications are working successfully."
    assert "ContentSid" not in data
    assert "ContentVariables" not in data


# ─────────────────────────────────────────────────────────
# T10: Production without ContentSid is rejected locally
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t10_production_without_contentsid_rejected_locally():
    """Production mode must reject missing ContentSid locally (no Twilio API call)."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
        sandbox_mode=False,
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        with patch("app.services.whatsapp.twilio_provider.settings.TWILIO_WHATSAPP_TEST_TEMPLATE", None):
            result = await provider.send_message(
                to_phone="+919876595952",
                message="Test",
                template_name="test",
            )

    assert result.success is False
    assert result.error_code == "MISSING_CONTENT_SID"
    assert result.is_transient is False
    mock_post.assert_not_called()
