import pytest
from unittest.mock import patch, AsyncMock
import httpx

from app.services.whatsapp.twilio_provider import TwilioWhatsAppProvider
from app.services.whatsapp.message_builder import (
    build_whatsapp_content,
    build_reminder_whatsapp_message,
    build_task_whatsapp_message,
    build_interview_whatsapp_message,
    build_test_whatsapp_message,
    WHATSAPP_ALLOWED_NOTIFICATION_TYPES,
)


@pytest.mark.asyncio
async def test_twilio_provider_send_success_mock():
    """Verify provider sends correctly formatted HTTP request and parses success status."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
    )

    mock_resp = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        json={"sid": "SM9876543210abcdef", "status": "queued"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await provider.send_message(
            to_phone="+919876543210",
            message="Test message",
        )

        assert res.success is True
        assert res.status == "queued"
        assert res.message_sid == "SM9876543210abcdef"
        assert res.is_transient is False

        # Verify call data
        mock_post.assert_called_once()
        kwargs = mock_post.call_args[1]
        assert kwargs["data"]["To"] == "whatsapp:+919876543210"
        assert kwargs["data"]["From"] == "whatsapp:+14155238886"
        assert kwargs["data"]["Body"] == "Test message"


@pytest.mark.asyncio
async def test_twilio_provider_transient_error_mock():
    """Verify HTTP 500 or 429 errors are marked as transient."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
    )

    mock_resp = httpx.Response(
        status_code=500,
        headers={"content-type": "application/json"},
        json={"code": 50000, "message": "Twilio Internal Server Error"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await provider.send_message(
            to_phone="+919876543210",
            message="Test message",
        )

        assert res.success is False
        assert res.is_transient is True
        assert "Internal Server Error" in res.error_message


@pytest.mark.asyncio
async def test_twilio_provider_permanent_error_mock():
    """Verify invalid phone or auth error is marked as permanent (not transient)."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
    )

    mock_resp = httpx.Response(
        status_code=400,
        headers={"content-type": "application/json"},
        json={"code": 21614, "message": "To number is not a valid WhatsApp user"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await provider.send_message(
            to_phone="+919876543210",
            message="Test message",
        )

        assert res.success is False
        assert res.is_transient is False
        assert res.error_code == "21614"


def test_twilio_webhook_signature_validation():
    """Verify Twilio HMAC-SHA1 signature verification logic."""
    import hmac
    import hashlib
    import base64

    auth_token = "secret_auth_token_xyz"
    url = "https://example.com/api/v1/whatsapp/webhook/status"
    params = {
        "MessageSid": "SM12345",
        "MessageStatus": "delivered",
        "AccountSid": "AC123",
    }

    # Compute genuine signature
    data_to_sign = url
    for k in sorted(params.keys()):
        data_to_sign += f"{k}{params[k]}"
    computed = hmac.new(auth_token.encode("utf-8"), data_to_sign.encode("utf-8"), hashlib.sha1).digest()
    valid_sig = base64.b64encode(computed).decode("ascii")

    # Positive check
    assert TwilioWhatsAppProvider.validate_webhook_signature(
        url=url,
        post_params=params,
        signature=valid_sig,
        auth_token=auth_token,
    ) is True

    # Negative check (tampered signature or params)
    assert TwilioWhatsAppProvider.validate_webhook_signature(
        url=url,
        post_params=params,
        signature="invalid_signature",
        auth_token=auth_token,
    ) is False


def test_whatsapp_message_builders_and_allowlist():
    """Verify message builders redact tokens and adhere to category allowlist."""
    assert "reminder" in WHATSAPP_ALLOWED_NOTIFICATION_TYPES
    assert "task_due" in WHATSAPP_ALLOWED_NOTIFICATION_TYPES
    assert "interview_alert" in WHATSAPP_ALLOWED_NOTIFICATION_TYPES
    assert "proactive_alert" in WHATSAPP_ALLOWED_NOTIFICATION_TYPES
    assert "test" in WHATSAPP_ALLOWED_NOTIFICATION_TYPES
    assert "arbitrary_custom_type" not in WHATSAPP_ALLOWED_NOTIFICATION_TYPES

    # Reminder
    rem_msg, vars_ = build_reminder_whatsapp_message("Prepare report", due_time_str="5:00 PM")
    assert "Reminder: Your reminder 'Prepare report' is due at 5:00 PM." in rem_msg

    # Interview
    int_msg, _ = build_interview_whatsapp_message("Google Tech Interview", scheduled_time="2:00 PM")
    assert "Interview Reminder: 'Google Tech Interview' is scheduled for 2:00 PM." in int_msg

    # Test
    test_msg, _ = build_test_whatsapp_message()
    assert "working successfully" in test_msg
    assert test_msg == "Your Personal AI Assistant WhatsApp notifications are working successfully."


@pytest.mark.asyncio
async def test_twilio_sandbox_mode_uses_body_without_contentsid():
    """Verify in Sandbox mode, send_message sends Body without requiring or passing ContentSid."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
        sandbox_mode=True,
    )

    mock_resp = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        json={"sid": "SMsandbox123", "status": "queued"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        body, vars_ = build_test_whatsapp_message()
        res = await provider.send_message(
            to_phone="+919876543210",
            message=body,
            template_name="test",
            template_variables=vars_,
        )

        assert res.success is True
        assert res.status == "queued"
        assert res.message_sid == "SMsandbox123"

        mock_post.assert_called_once()
        kwargs = mock_post.call_args[1]
        data = kwargs["data"]

        assert data["From"] == "whatsapp:+14155238886"
        assert data["To"] == "whatsapp:+919876543210"
        assert data["Body"] == "Your Personal AI Assistant WhatsApp notifications are working successfully."
        assert "ContentSid" not in data
        assert "ContentVariables" not in data


@pytest.mark.asyncio
async def test_twilio_production_mode_requires_and_uses_contentsid():
    """Verify in Production mode, send_message uses ContentSid & ContentVariables when configured."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
        sandbox_mode=False,
    )

    mock_resp = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        json={"sid": "SMprod123", "status": "queued"},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with patch("app.services.whatsapp.twilio_provider.settings.TWILIO_WHATSAPP_REMINDER_TEMPLATE", "HX1234567890abcdef"):
            res = await provider.send_message(
                to_phone="+919876543210",
                message="Reminder: Prepare budget report",
                template_name="reminder",
                template_variables={"1": "Prepare budget report", "2": "5:00 PM"},
            )

            assert res.success is True
            assert res.status == "queued"
            assert res.message_sid == "SMprod123"

            mock_post.assert_called_once()
            kwargs = mock_post.call_args[1]
            data = kwargs["data"]

            assert data["From"] == "whatsapp:+14155238886"
            assert data["To"] == "whatsapp:+919876543210"
            assert data["ContentSid"] == "HX1234567890abcdef"
            assert '{"1": "Prepare budget report", "2": "5:00 PM"}' in data["ContentVariables"]
            assert "Body" not in data


@pytest.mark.asyncio
async def test_twilio_production_mode_rejects_missing_contentsid():
    """Verify in Production mode, missing ContentSid is rejected with permanent error without network call."""
    provider = TwilioWhatsAppProvider(
        account_sid="AC1234567890abcdef",
        auth_token="authtoken123456",
        from_number="whatsapp:+14155238886",
        sandbox_mode=False,
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Template is not configured in settings (defaults to None)
        with patch("app.services.whatsapp.twilio_provider.settings.TWILIO_WHATSAPP_REMINDER_TEMPLATE", None):
            res = await provider.send_message(
                to_phone="+919876543210",
                message="Reminder: Prepare budget report",
                template_name="reminder",
                template_variables={"1": "Prepare budget report", "2": "5:00 PM"},
            )

            assert res.success is False
            assert res.status == "failed"
            assert res.error_code == "MISSING_CONTENT_SID"
            assert res.is_transient is False
            assert "ContentSid required" in res.error_message

            mock_post.assert_not_called()

