"""
Unit tests for Milestone 9 Production Configuration Invariants.
Validates that production environment rejects default secrets, SQLite, missing Redis,
wildcard CORS, and insecure cookies.
"""
import base64
import os
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings


def _valid_prod_kwargs() -> dict:
    """Returns valid kwargs satisfying all production invariants."""
    valid_key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    return {
        "ENVIRONMENT": "production",
        "SECRET_KEY": "p" * 35 + "_high_entropy_signing_token_9842",
        "TOKEN_ENCRYPTION_KEY": valid_key,
        "DATABASE_URL": "postgresql+asyncpg://prod_user:prod_pass@db.internal:5432/prod_db",
        "RATE_LIMIT_ENABLED": True,
        "RATE_LIMIT_STORAGE": "redis",
        "REDIS_URL": "redis://:secure_redis_pwd@redis.internal:6379/0",
        "GOOGLE_CLIENT_ID": "prod-client-id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "prod-client-secret-secure-12345",
        "GEMINI_API_KEY": "AIzaSyProductionKey-ABCDEFG-12345",
        "ALLOWED_ORIGINS": ["https://assistant.example.com"],
        "SESSION_COOKIE_SECURE": True,
        "TRUSTED_PROXY_IPS": ["10.0.0.1"],
        "VAPID_PUBLIC_KEY": "BPx_test_vapid_public_key_for_production_testing_1234567890",
        "VAPID_PRIVATE_KEY": "test_vapid_private_key_for_production_testing_1234567890",
    }


def test_production_rejects_default_secret_key():
    """Production mode must reject default or insecure SECRET_KEY."""
    kwargs = _valid_prod_kwargs()
    kwargs["SECRET_KEY"] = "super-secret-session-signing-key-minimum-32-chars-change-in-prod"
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "SECRET_KEY cannot contain default or insecure substrings" in str(exc_info.value)


def test_production_rejects_short_secret_key():
    """Production mode must reject SECRET_KEY with length < 32."""
    kwargs = _valid_prod_kwargs()
    kwargs["SECRET_KEY"] = "short-key-123"
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "SECRET_KEY must be at least 32 characters" in str(exc_info.value)


def test_production_requires_fernet_token_encryption_key():
    """Production mode requires explicit TOKEN_ENCRYPTION_KEY."""
    kwargs = _valid_prod_kwargs()
    kwargs["TOKEN_ENCRYPTION_KEY"] = ""
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "TOKEN_ENCRYPTION_KEY must be explicitly set" in str(exc_info.value)


def test_production_rejects_invalid_fernet_key():
    """Production mode rejects malformed base64 Fernet key."""
    kwargs = _valid_prod_kwargs()
    kwargs["TOKEN_ENCRYPTION_KEY"] = "not-a-valid-fernet-key"
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "TOKEN_ENCRYPTION_KEY must be a valid 32-byte base64 Fernet key" in str(exc_info.value)


def test_production_rejects_sqlite_database_url():
    """Production mode strictly forbids SQLite."""
    kwargs = _valid_prod_kwargs()
    kwargs["DATABASE_URL"] = "sqlite+aiosqlite:///./prod.db"
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "SQLite is forbidden in production; PostgreSQL is required" in str(exc_info.value)


def test_production_requires_redis_url_when_rate_limit_enabled():
    """Production mode requires REDIS_URL when rate limiting is enabled."""
    kwargs = _valid_prod_kwargs()
    kwargs["REDIS_URL"] = None
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "REDIS_URL must be configured when RATE_LIMIT_ENABLED is true in production" in str(exc_info.value)


def test_production_rejects_memory_storage_in_production():
    """Production mode strictly forbids in-memory rate limit fallback."""
    kwargs = _valid_prod_kwargs()
    kwargs["RATE_LIMIT_STORAGE"] = "memory"
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "In-memory rate limiting is forbidden in production; Redis is required" in str(exc_info.value)


def test_production_rejects_wildcard_cors():
    """Production mode strictly forbids wildcard CORS origins."""
    kwargs = _valid_prod_kwargs()
    kwargs["ALLOWED_ORIGINS"] = ["*"]
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "Wildcard CORS ('*') is forbidden in production" in str(exc_info.value)


def test_production_requires_secure_session_cookies():
    """Production mode requires SESSION_COOKIE_SECURE=True."""
    kwargs = _valid_prod_kwargs()
    kwargs["SESSION_COOKIE_SECURE"] = False
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "SESSION_COOKIE_SECURE must be True in production" in str(exc_info.value)


def test_valid_production_config_succeeds():
    """Valid production configuration instantiates without error."""
    kwargs = _valid_prod_kwargs()
    s = Settings(**kwargs)
    assert s.ENVIRONMENT == "production"
    assert s.SESSION_COOKIE_SECURE is True
    assert s.DATABASE_URL.startswith("postgresql")
    assert s.RATE_LIMIT_STORAGE == "redis"
    assert s.VAPID_PUBLIC_KEY is not None


def test_production_requires_vapid_keys():
    """Production mode requires explicit VAPID keys when Web Push is enabled."""
    kwargs = _valid_prod_kwargs()
    kwargs["VAPID_PUBLIC_KEY"] = None
    with pytest.raises(ValidationError) as exc_info:
        Settings(**kwargs)
    assert "Production VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY must be explicitly configured" in str(exc_info.value)
