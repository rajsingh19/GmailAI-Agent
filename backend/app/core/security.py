"""
Cryptographic and Security Utilities.
Handles AES Fernet token encryption at rest, CSRF state generation/validation,
and server-side session token signing.
"""
import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken
import jwt

from app.core.config import settings


class TokenEncryptionError(Exception):
    """Raised when token encryption or decryption fails."""
    pass


def _get_fernet_key() -> bytes:
    """
    Retrieves or derives a valid 32-byte url-safe base64 Fernet key.
    Uses TOKEN_ENCRYPTION_KEY if provided; otherwise derives deterministically from SECRET_KEY.
    """
    raw_key = settings.TOKEN_ENCRYPTION_KEY.strip()
    if raw_key:
        try:
            # Validate it is 32 bytes when base64 decoded
            decoded = base64.urlsafe_b64decode(raw_key.encode("ascii"))
            if len(decoded) == 32:
                return raw_key.encode("ascii")
        except Exception:
            pass

    # Deterministic SHA256 derivation from SECRET_KEY for dev environments
    derived = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(derived)


_FERNET_INSTANCE = Fernet(_get_fernet_key())


class SecurityManager:
    """Encapsulates token encryption, CSRF state verification, and session management."""

    @staticmethod
    def encrypt_token(plain_token: str) -> str:
        """
        Encrypts an OAuth token (access or refresh) using Fernet AES-128-CBC + HMAC-SHA256.
        Returns URL-safe base64 string.
        """
        if not plain_token:
            return ""
        try:
            encrypted_bytes = _FERNET_INSTANCE.encrypt(plain_token.encode("utf-8"))
            return encrypted_bytes.decode("ascii")
        except Exception as e:
            raise TokenEncryptionError(f"Failed to encrypt token: {e}") from e

    @staticmethod
    def decrypt_token(encrypted_token: str) -> str:
        """
        Decrypts an encrypted token.
        Raises TokenEncryptionError if ciphertext is invalid, tampered, or corrupted.
        """
        if not encrypted_token:
            return ""
        try:
            decrypted_bytes = _FERNET_INSTANCE.decrypt(encrypted_token.encode("ascii"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken as e:
            raise TokenEncryptionError("Invalid or tampered encrypted token payload") from e
        except Exception as e:
            raise TokenEncryptionError(f"Failed to decrypt token: {e}") from e

    @staticmethod
    def encrypt_bytes(plain_bytes: bytes) -> bytes:
        """
        Encrypts raw binary data (e.g. resume files at rest) using authenticated Fernet AES-128-CBC + HMAC-SHA256.
        Returns encrypted bytes.
        """
        if not plain_bytes:
            return b""
        try:
            return _FERNET_INSTANCE.encrypt(plain_bytes)
        except Exception as e:
            raise TokenEncryptionError(f"Failed to encrypt file bytes: {e}") from e

    @staticmethod
    def decrypt_bytes(encrypted_bytes: bytes) -> bytes:
        """
        Decrypts encrypted binary data.
        Raises TokenEncryptionError if ciphertext is invalid, tampered, or corrupted.
        """
        if not encrypted_bytes:
            return b""
        try:
            return _FERNET_INSTANCE.decrypt(encrypted_bytes)
        except InvalidToken as e:
            raise TokenEncryptionError("Invalid or tampered encrypted file payload") from e
        except Exception as e:
            raise TokenEncryptionError(f"Failed to decrypt file bytes: {e}") from e

    # -------------------------------------------------------------------------
    # OAuth CSRF State Protection
    # -------------------------------------------------------------------------

    @staticmethod
    def generate_oauth_state(ttl_seconds: int = 600) -> str:
        """
        Generates a signed, timestamped, cryptographically random state token.
        Format: <random_hex>.<expire_timestamp>.<hmac_signature>
        """
        random_part = secrets.token_hex(24)
        expires_at = int(time.time()) + ttl_seconds
        payload = f"{random_part}.{expires_at}"
        signature = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{payload}.{signature}"

    @staticmethod
    def validate_oauth_state_with_reason(
        state: Optional[str],
        expected_state: Optional[str],
    ) -> Tuple[bool, str]:
        """
        Validates the OAuth state parameter with detailed status reason.
        Supports single state or pipe-separated multiple active states from cookie.
        Checks:
        1. State and cookie presence.
        2. Constant-time match against cookie state.
        3. HMAC-SHA256 signature verification.
        4. Expiration against 10-minute TTL.
        Returns:
        (True, "valid") or (False, "<reason>")
        """
        if not state:
            return False, "missing_callback_state"
        if not expected_state:
            return False, "missing_state_cookie"

        # Split multiple active states if present
        candidate_states = [s.strip() for s in expected_state.split("|") if s.strip()]
        if not candidate_states:
            return False, "empty_state_cookie"

        # Find matching state candidate using constant-time comparison
        matching_state = None
        for candidate in candidate_states:
            if hmac.compare_digest(state, candidate):
                matching_state = candidate
                break

        if not matching_state:
            return False, "state_mismatch"

        parts = matching_state.split(".")
        if len(parts) != 3:
            return False, "malformed_state"

        random_part, expires_at_str, signature = parts
        payload = f"{random_part}.{expires_at_str}"

        # Verify cryptographic signature
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            return False, "signature_invalid"

        # Verify expiration
        try:
            expires_at = int(expires_at_str)
            if time.time() > expires_at:
                return False, "state_expired"
        except ValueError:
            return False, "invalid_timestamp"

        return True, "valid"

    @staticmethod
    def validate_oauth_state(state: Optional[str], expected_state: Optional[str]) -> bool:
        """
        Validates the OAuth state parameter:
        1. Checks state presence and non-emptiness.
        2. Verifies exact match against expected state stored in session cookie.
        3. Verifies HMAC-SHA256 cryptographic signature.
        4. Verifies state has not expired.
        """
        valid, _ = SecurityManager.validate_oauth_state_with_reason(state, expected_state)
        return valid

    # -------------------------------------------------------------------------
    # Server-side Session Management
    # -------------------------------------------------------------------------

    @staticmethod
    def create_session_token(user_id: str, max_age_seconds: Optional[int] = None) -> str:
        """
        Creates a signed JWT session token containing user_id.
        """
        age = max_age_seconds or settings.SESSION_MAX_AGE_SECONDS
        payload = {
            "sub": user_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + age,
            "iss": settings.PROJECT_NAME,
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

    @staticmethod
    def decode_session_token(token: Optional[str]) -> Optional[str]:
        """
        Decodes session token and returns user_id if valid. Returns None if invalid or expired.
        """
        if not token:
            return None
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                options={"require": ["sub", "exp"]},
            )
            return payload.get("sub")
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None


# -----------------------------------------------------------------------------
# SQLAlchemy Transparent Column Encryption at Rest
# -----------------------------------------------------------------------------
import json
from typing import Any
from sqlalchemy.types import TypeDecorator, Text


class EncryptedText(TypeDecorator):
    """
    SQLAlchemy TypeDecorator for authenticated Fernet encryption at rest for text fields.
    Automatically encrypts on save and decrypts on load using server-side SecurityManager.
    Transparently handles plaintext legacy values during migrations.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        if not value:
            return ""
        try:
            return SecurityManager.encrypt_token(value)
        except Exception as e:
            raise TokenEncryptionError(f"Failed to encrypt text field: {e}") from e

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        if not value:
            return ""
        try:
            return SecurityManager.decrypt_token(value)
        except Exception:
            # Fallback for unencrypted legacy rows or test fixtures
            return value


class EncryptedJSON(TypeDecorator):
    """
    SQLAlchemy TypeDecorator for authenticated Fernet encryption at rest for JSON dict/list fields.
    Serializes JSON to string, encrypts on save, and decrypts/deserializes on load.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> Optional[str]:
        if value is None:
            return None
        try:
            json_str = json.dumps(value)
            return SecurityManager.encrypt_token(json_str)
        except Exception as e:
            raise TokenEncryptionError(f"Failed to encrypt JSON field: {e}") from e

    def process_result_value(self, value: Optional[str], dialect) -> Any:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return value
        if not value:
            return {}
        try:
            decrypted = SecurityManager.decrypt_token(value)
            return json.loads(decrypted)
        except Exception:
            try:
                return json.loads(value)
            except Exception:
                return {}

