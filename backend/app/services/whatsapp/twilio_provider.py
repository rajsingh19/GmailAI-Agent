"""
Twilio WhatsApp Delivery Provider implementation.
Encapsulates all communication with Twilio REST API, handles sandbox and production modes,
implements Twilio signature verification for webhooks, and classifies transient vs permanent errors.
"""
import base64
import hashlib
import hmac
import logging
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.phone import normalize_phone_number, mask_phone_number
from app.services.whatsapp.base import (
    WhatsAppDeliveryProvider,
    WhatsAppDeliveryResult,
    WhatsAppStatusResult,
)

logger = logging.getLogger(settings.PROJECT_NAME)

# Permanent error codes that should NOT be retried:
# 21211: Invalid 'To' Phone Number
# 21614: 'To' number is not a valid mobile number / not registered for WhatsApp
# 20003: Authentication Error
# 63007: Twilio WhatsApp sandbox opt-in missing
# 63016: Template parameters mismatch
PERMANENT_TWILIO_ERROR_CODES = {
    21211, 21408, 21610, 21614, 20003, 20404, 63007, 63016, 63032
}


class TwilioWhatsAppProvider(WhatsAppDeliveryProvider):
    """
    Twilio WhatsApp Provider implementing WhatsAppDeliveryProvider.
    Uses async httpx client with connection timeouts and bounded retries.
    """

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        sandbox_mode: Optional[bool] = None,
    ):
        self.account_sid = (settings.TWILIO_ACCOUNT_SID or "").strip() if account_sid is None else account_sid.strip()
        self.auth_token = (settings.TWILIO_AUTH_TOKEN or "").strip() if auth_token is None else auth_token.strip()
        self.from_number = (settings.TWILIO_WHATSAPP_FROM or "whatsapp:+14155238886").strip() if from_number is None else from_number.strip()
        self.api_key = (settings.TWILIO_API_KEY or "").strip() if api_key is None else api_key.strip()
        self.api_secret = (settings.TWILIO_API_SECRET or "").strip() if api_secret is None else api_secret.strip()
        self.sandbox_mode = settings.TWILIO_SANDBOX_MODE if sandbox_mode is None else sandbox_mode

    def is_configured(self) -> bool:
        """Returns True if minimum required credentials and from_number exist."""
        has_auth = bool(self.account_sid and (self.auth_token or (self.api_key and self.api_secret)))
        has_from = bool(self.from_number)
        return has_auth and has_from

    def validate_configuration(self) -> Tuple[bool, Optional[str]]:
        """Validates credentials presence without leaking values."""
        if not self.account_sid:
            return False, "TWILIO_ACCOUNT_SID is missing."
        if not self.auth_token and not (self.api_key and self.api_secret):
            return False, "TWILIO_AUTH_TOKEN or TWILIO_API_KEY/SECRET is missing."
        if not self.from_number:
            return False, "TWILIO_WHATSAPP_FROM sender is missing."
        return True, None

    def _get_auth_credentials(self) -> Tuple[str, str]:
        """Returns basic auth username and password."""
        if self.api_key and self.api_secret:
            return (self.api_key, self.api_secret)
        return (self.account_sid, self.auth_token)

    def _format_whatsapp_number(self, phone: str) -> str:
        """Ensures phone number has whatsapp: prefix and E.164 normalization."""
        clean = phone.strip()
        if clean.startswith("whatsapp:"):
            clean = clean[len("whatsapp:"):]
        normalized = normalize_phone_number(clean)
        return f"whatsapp:{normalized}"

    async def send_message(
        self,
        to_phone: str,
        message: str,
        template_name: Optional[str] = None,
        template_variables: Optional[Dict[str, str]] = None,
        status_callback: Optional[str] = None,
    ) -> WhatsAppDeliveryResult:
        """
        Submits outbound WhatsApp message to Twilio REST API.
        Never reports 'delivered' upon submission—returns 'submitted' or 'queued'.

        In Sandbox mode (TWILIO_SANDBOX_MODE=true):
            Sends free-form Body-based message when recipient is in active sandbox session.
            Does not require ContentSid.

        In Production mode (TWILIO_SANDBOX_MODE=false):
            Requires approved Content Template (ContentSid). Rejects if ContentSid is missing.
        """
        valid, err = self.validate_configuration()
        if not valid:
            logger.warning("Twilio send aborted: %s", err)
            return WhatsAppDeliveryResult(
                success=False,
                status="failed",
                error_code="CONFIG_ERROR",
                error_message=err,
                is_transient=False,
            )

        try:
            to_formatted = self._format_whatsapp_number(to_phone)
            from_formatted = (
                self.from_number
                if self.from_number.startswith("whatsapp:")
                else f"whatsapp:{self.from_number}"
            )
        except Exception as e:
            return WhatsAppDeliveryResult(
                success=False,
                status="failed",
                error_code="INVALID_PHONE",
                error_message=f"Phone validation failed: {str(e)}",
                is_transient=False,
            )

        api_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        auth = self._get_auth_credentials()

        data: Dict[str, Any] = {
            "From": from_formatted,
            "To": to_formatted,
        }

        # Sandbox Mode vs Production Mode
        if self.sandbox_mode:
            # SANDBOX MODE: Twilio Sandbox uses free-form Body messages during an active session
            data["Body"] = message
        else:
            # PRODUCTION MODE: Business-initiated messages require approved WhatsApp Content Templates (ContentSid)
            template_sid = None
            if template_name:
                template_sid = getattr(settings, f"TWILIO_WHATSAPP_{template_name.upper()}_TEMPLATE", None)
                if not template_sid and template_name.upper() == "TASK":
                    template_sid = getattr(settings, "TWILIO_WHATSAPP_TASK_DUE_TEMPLATE", None)

            if template_sid:
                data["ContentSid"] = template_sid
                if template_variables:
                    import json
                    data["ContentVariables"] = json.dumps(template_variables)
            else:
                logger.warning(
                    "Production WhatsApp message rejected: missing ContentSid for template '%s'",
                    template_name,
                )
                return WhatsAppDeliveryResult(
                    success=False,
                    status="failed",
                    error_code="MISSING_CONTENT_SID",
                    error_message=f"ContentSid required for production WhatsApp notification type '{template_name or 'unspecified'}'.",
                    is_transient=False,
                )

        callback_url = status_callback or settings.TWILIO_STATUS_CALLBACK_URL
        if callback_url:
            data["StatusCallback"] = callback_url

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    api_url,
                    data=data,
                    auth=auth,
                )

            resp_json = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

            if resp.status_code in (200, 201):
                sid = resp_json.get("sid")
                twilio_status = resp_json.get("status", "queued")
                logger.info(
                    "Twilio WhatsApp message accepted. SID=%s status=%s to=%s",
                    sid,
                    twilio_status,
                    mask_phone_number(to_phone),
                )
                return WhatsAppDeliveryResult(
                    success=True,
                    status=twilio_status if twilio_status in ("queued", "sent", "submitted") else "submitted",
                    message_sid=sid,
                    error_code=None,
                    error_message=None,
                    is_transient=False,
                )
            else:
                error_code = resp_json.get("code")
                error_msg = resp_json.get("message") or resp.text
                status_code = resp.status_code

                is_transient = (status_code >= 500 or status_code == 429) and (error_code not in PERMANENT_TWILIO_ERROR_CODES)

                logger.warning(
                    "Twilio WhatsApp send failed: HTTP %s code=%s msg=%s to=%s",
                    status_code,
                    error_code,
                    error_msg[:100],
                    mask_phone_number(to_phone),
                )
                return WhatsAppDeliveryResult(
                    success=False,
                    status="failed",
                    message_sid=resp_json.get("sid"),
                    error_code=str(error_code or status_code),
                    error_message=str(error_msg)[:250],
                    is_transient=is_transient,
                )

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("Twilio WhatsApp connection timeout/error to %s: %s", mask_phone_number(to_phone), exc)
            return WhatsAppDeliveryResult(
                success=False,
                status="failed",
                error_code="TIMEOUT",
                error_message="Connection to Twilio service timed out.",
                is_transient=True,
            )
        except Exception as exc:
            logger.exception("Unexpected error dispatching Twilio WhatsApp message: %s", exc)
            return WhatsAppDeliveryResult(
                success=False,
                status="failed",
                error_code="INTERNAL_ERROR",
                error_message=str(exc)[:250],
                is_transient=True,
            )

    async def get_delivery_status(self, message_sid: str) -> WhatsAppStatusResult:
        """Queries delivery status of a previously submitted message SID."""
        valid, err = self.validate_configuration()
        if not valid or not message_sid:
            return WhatsAppStatusResult(
                message_sid=message_sid,
                status="undelivered",
                error_code="CONFIG_ERROR",
                error_message=err or "Invalid message SID",
            )

        api_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages/{message_sid}.json"
        auth = self._get_auth_credentials()

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(api_url, auth=auth)

            if resp.status_code == 200:
                data = resp.json()
                return WhatsAppStatusResult(
                    message_sid=message_sid,
                    status=data.get("status", "queued"),
                    error_code=str(data.get("error_code")) if data.get("error_code") else None,
                    error_message=data.get("error_message"),
                )
            else:
                return WhatsAppStatusResult(
                    message_sid=message_sid,
                    status="failed",
                    error_code=str(resp.status_code),
                    error_message=resp.text[:100],
                )
        except Exception as exc:
            return WhatsAppStatusResult(
                message_sid=message_sid,
                status="failed",
                error_code="QUERY_ERROR",
                error_message=str(exc)[:100],
            )

    @classmethod
    def validate_webhook_signature(
        cls,
        url: str,
        post_params: Dict[str, Any],
        signature: Optional[str],
        auth_token: Optional[str] = None,
    ) -> bool:
        """
        Cryptographically validates Twilio HMAC-SHA1 webhook signature according to Twilio standard:
        1. Take the full URL (as configured in Twilio webhook).
        2. Sort POST parameters alphabetically by parameter name.
        3. Append parameter name and value directly to the URL string.
        4. Sign the resulting UTF-8 data with HMAC-SHA1 using auth_token.
        5. Base64 encode and compare with X-Twilio-Signature header using constant-time comparison.
        """
        expected_token = (auth_token or settings.TWILIO_AUTH_TOKEN or "").strip()
        if not expected_token or not signature or not url:
            return False

        # Build validation string
        data_to_sign = url
        for key in sorted(post_params.keys()):
            data_to_sign += f"{key}{post_params[key]}"

        computed = hmac.new(
            expected_token.encode("utf-8"),
            data_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()

        computed_b64 = base64.b64encode(computed).decode("ascii")
        return hmac.compare_digest(computed_b64, signature.strip())
