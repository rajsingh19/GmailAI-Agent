import base64
import hashlib
import hmac
import json
import time
import uuid
import logging
from typing import Set, Optional, Dict, Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class ConfirmationSecurityError(Exception):
    """Raised when confirmation challenge validation fails."""
    pass


class ConfirmationService:
    """
    Cryptographic server-issued one-time confirmation challenge service.
    Binds high-risk actions (such as deletion) to the exact authenticated user,
    tool name, target resource ID, action, and short TTL.
    Prevents replay attacks by tracking consumed challenge nonces.
    """

    _consumed_challenges: Set[str] = set()

    @classmethod
    def _sign_payload(cls, payload_bytes: bytes) -> str:
        """Generates HMAC-SHA256 signature using application SECRET_KEY."""
        key = settings.SECRET_KEY.encode("utf-8")
        sig = hmac.new(key, payload_bytes, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")

    @classmethod
    def issue_challenge(
        cls,
        user_id: str,
        tool_name: str,
        target_id: str,
        action: str = "delete",
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """
        Creates a signed, time-limited confirmation token.
        Token is bound specifically to (user_id, tool_name, target_id, action).
        """
        ttl = ttl_seconds or settings.CONFIRMATION_TOKEN_TTL_SECONDS
        now = int(time.time())
        challenge_id = str(uuid.uuid4())

        payload = {
            "cid": challenge_id,
            "uid": user_id,
            "tool": tool_name,
            "tid": str(target_id),
            "act": action,
            "iat": now,
            "exp": now + ttl,
        }

        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
        sig_b64 = cls._sign_payload(payload_bytes)

        # Format: <payload_b64>.<sig_b64>
        return f"{payload_b64}.{sig_b64}"

    @classmethod
    def verify_and_consume(
        cls,
        token: str,
        user_id: str,
        tool_name: str,
        target_id: str,
        action: str = "delete",
    ) -> bool:
        """
        Verifies the cryptographic signature, expiration, target match, user match,
        and single-use status of the confirmation token.
        Consumes the token immediately upon success to prevent replay attacks.
        """
        if not token or not isinstance(token, str):
            logger.warning("Empty or invalid confirmation token format provided")
            return False

        parts = token.split(".")
        if len(parts) != 2:
            logger.warning("Malformed confirmation token structure")
            return False

        payload_b64, sig_b64 = parts

        # Add base64 padding if needed
        def _pad(s: str) -> str:
            return s + "=" * ((4 - len(s) % 4) % 4)

        try:
            payload_bytes = base64.urlsafe_b64decode(_pad(payload_b64))
            expected_sig = cls._sign_payload(payload_bytes)

            # Constant-time signature comparison to prevent timing attacks
            if not hmac.compare_digest(sig_b64, expected_sig):
                logger.warning("Confirmation token signature mismatch")
                return False

            payload: Dict[str, Any] = json.loads(payload_bytes.decode("utf-8"))

            challenge_id = payload.get("cid")
            token_uid = payload.get("uid")
            token_tool = payload.get("tool")
            token_tid = payload.get("tid")
            token_act = payload.get("act")
            token_exp = payload.get("exp", 0)

            now = int(time.time())

            # 1. Expiration check
            if now > token_exp:
                logger.info("Confirmation token expired (now=%d, exp=%d)", now, token_exp)
                return False

            # 2. Replay check (single-use challenge nonce)
            if not challenge_id or challenge_id in cls._consumed_challenges:
                logger.warning("Confirmation token challenge already consumed (cid=%s)", challenge_id)
                return False

            # 3. User isolation check
            if token_uid != user_id:
                logger.warning("Confirmation token user mismatch (token_uid=%s, auth_uid=%s)", token_uid, user_id)
                return False

            # 4. Tool specification check
            if token_tool != tool_name:
                logger.warning("Confirmation token tool mismatch (token_tool=%s, req_tool=%s)", token_tool, tool_name)
                return False

            # 5. Target ID check
            if str(token_tid) != str(target_id):
                logger.warning("Confirmation token target ID mismatch (token_tid=%s, req_tid=%s)", token_tid, target_id)
                return False

            # 6. Action check
            if token_act != action:
                logger.warning("Confirmation token action mismatch (token_act=%s, req_act=%s)", token_act, action)
                return False

            # Token is fully valid: consume it immediately
            cls._consumed_challenges.add(challenge_id)
            return True

        except Exception as exc:
            logger.warning("Failed to decode or verify confirmation token: %s", exc)
            return False

    @classmethod
    def reset_consumed_tokens_for_testing(cls) -> None:
        """Helper to clear consumed challenge set during test fixtures."""
        cls._consumed_challenges.clear()
