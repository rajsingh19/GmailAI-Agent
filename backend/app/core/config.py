import base64
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Personal AI Assistant"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "text" or "json"

    # Server binding (Strictly Port 8000 for local dev)
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Frontend URL for OAuth redirects
    FRONTEND_URL: str = "http://localhost:5173"

    # CORS configuration
    ALLOWED_ORIGINS: Union[str, List[str]] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # Trusted Upstream Proxies for Client IP Resolution
    TRUSTED_PROXY_IPS: Union[str, List[str]] = ["127.0.0.1"]

    @field_validator("TRUSTED_PROXY_IPS", mode="before")
    @classmethod
    def assemble_trusted_proxies(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # Security & Session Configuration
    SECRET_KEY: str = "super-secret-session-signing-key-minimum-32-chars-change-in-prod"
    TOKEN_ENCRYPTION_KEY: str = ""  # Base64 Fernet key, auto-derived in dev if empty
    SESSION_COOKIE_NAME: str = "ai_assistant_session"
    SESSION_COOKIE_SECURE: bool = False  # Mandatory True in production
    SESSION_COOKIE_SAMESITE: str = "lax"
    SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 7  # 7 days
    STATE_COOKIE_NAME: str = "oauth_state_csrf"
    STATE_COOKIE_MAX_AGE: int = 600  # 10 minutes

    # Rate Limiting Configuration (Milestone 9)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_STORAGE: str = "redis"  # "redis" or "memory" (memory allowed only in dev/test)
    REDIS_URL: Optional[str] = None
    REDIS_SOCKET_TIMEOUT: float = 2.0
    REDIS_CONNECT_TIMEOUT: float = 2.0
    RATE_LIMIT_DEFAULT_LIMIT: int = 60
    RATE_LIMIT_DEFAULT_WINDOW: int = 60
    RATE_LIMIT_AUTH_LIMIT: int = 10
    RATE_LIMIT_AUTH_WINDOW: int = 60
    RATE_LIMIT_ACTION_LIMIT: int = 10
    RATE_LIMIT_ACTION_WINDOW: int = 60

    # Content Security Policy & Security Headers
    CSP_REPORT_ONLY: bool = False

    # Metrics & Prometheus Configuration
    METRICS_ENABLED: bool = True
    METRICS_SECRET_TOKEN: Optional[str] = None

    # Database Configuration (SQLite default with PostgreSQL support)
    DATABASE_URL: str = "sqlite+aiosqlite:///./ai_assistant.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # Google OAuth 2.0 Credentials
    GOOGLE_CREDENTIALS_PATH: Optional[str] = None
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # OAuth Endpoints
    GOOGLE_AUTH_URI: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URI: str = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URI: str = "https://www.googleapis.com/oauth2/v2/userinfo"
    GOOGLE_REVOKE_URI: str = "https://oauth2.googleapis.com/revoke"

    # OAuth Scopes: strictly read-only Gmail + Calendar + standard identity profile
    OAUTH_SCOPES: List[str] = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]

    # AI Provider configuration (Milestone 6)
    GEMINI_API_KEY: str = ""
    AI_MODEL_NAME: str = "gemini-3.6-flash"
    GEMINI_MODEL: Optional[str] = None  # Optional override

    # Embedding & RAG Configuration (Milestone 7)
    EMBEDDING_PROVIDER: str = "gemini"
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSIONS: int = 768
    RAG_CHUNK_SIZE: int = 500
    RAG_CHUNK_OVERLAP: int = 75
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.65
    MAX_GMAIL_MESSAGES_PER_INGEST: int = 30
    MAX_CALENDAR_EVENTS_PER_INGEST: int = 30
    MAX_TASKS_PER_INGEST: int = 50
    MAX_REMINDERS_PER_INGEST: int = 50
    MAX_TOTAL_DOCS_PER_REINDEX: int = 100
    MAX_TOTAL_CHUNKS_PER_INGEST: int = 500
    EMBEDDING_BATCH_SIZE: int = 20
    INGESTION_TIMEOUT_SECONDS: int = 45
    MAX_DOCUMENT_INGEST_CHARS: int = 20000

    # Agent Execution, Context & Timeout Limits
    MAX_TOOL_CALLS_PER_TURN: int = 5
    TOOL_TIMEOUT_SECONDS: int = 10
    AGENT_TIMEOUT_SECONDS: int = 30
    MAX_AGENT_MESSAGE_LENGTH: int = 4000
    MAX_HISTORY_MESSAGES: int = 10
    MAX_HISTORY_CHARS: int = 8000
    MAX_TOOL_RESULT_CHARS: int = 4000
    CONFIRMATION_TOKEN_TTL_SECONDS: int = 300
    # Milestone 10: Voice & Multimodal Interaction Settings
    VOICE_ENABLED: bool = True
    STT_PROVIDER: str = "gemini"  # "gemini", "mock"
    GEMINI_STT_MODEL: str = "gemini-3.6-flash"
    TTS_PROVIDER: str = "mock"  # "google", "mock"
    GOOGLE_TTS_VOICE: str = "en-US-Journey-F"
    GOOGLE_TTS_LANGUAGE: str = "en-US"
    MAX_AUDIO_BYTES: int = 10 * 1024 * 1024  # 10 MB default
    MAX_AUDIO_DURATION_SECONDS: int = 60
    MAX_TRANSCRIPT_CHARS: int = 2000
    MAX_TTS_CHARS: int = 1000
    VOICE_REQUEST_TIMEOUT: int = 30
    VOICE_AUDIO_PERSISTENCE: bool = False
    RATE_LIMIT_VOICE_LIMIT: int = 20
    RATE_LIMIT_VOICE_WINDOW: int = 60

    # Milestone 11: Long-Term Personal Memory
    MEMORY_ENABLED_DEFAULT: bool = False
    MEMORY_MAX_ITEMS_PER_CONTEXT: int = 10
    MEMORY_MAX_CONTEXT_CHARS: int = 2000
    MEMORY_SEARCH_LIMIT: int = 20
    MEMORY_MAX_KEY_LENGTH: int = 100
    MEMORY_MAX_VALUE_LENGTH: int = 2000
    MEMORY_CONFIDENCE_THRESHOLD: float = 0.5
    RATE_LIMIT_MEMORY_LIMIT: int = 30
    RATE_LIMIT_MEMORY_WINDOW: int = 60

    # Milestone 12: Personalization Intelligence & Policy Layer
    PERSONALIZATION_ENABLED_DEFAULT: bool = False
    PERSONALIZATION_LEVEL_DEFAULT: str = "MEDIUM"
    PERSONALIZATION_RELEVANCE_THRESHOLD: float = 15.0
    PERSONALIZATION_MAX_CONTEXT_CHARS: int = 1000
    PERSONALIZATION_PREVIEW_LIMIT: int = 10
    PERSONALIZATION_SESSION_OVERRIDE_TTL_SECONDS: int = 3600
    PERSONALIZATION_CACHE_TTL_SECONDS: int = 300
    RATE_LIMIT_PERSONALIZATION_LIMIT: int = 30
    RATE_LIMIT_PERSONALIZATION_WINDOW: int = 60

    @property
    def effective_model_name(self) -> str:
        """Returns the configured model name, prioritizing GEMINI_MODEL over AI_MODEL_NAME."""
        return self.GEMINI_MODEL or self.AI_MODEL_NAME

    @property
    def effective_embedding_model(self) -> str:
        """Returns the configured embedding model name."""
        return self.EMBEDDING_MODEL

    @model_validator(mode="after")
    def validate_production_invariants(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            # 1. SECRET_KEY validation
            if len(self.SECRET_KEY) < 32:
                raise ValueError("Production SECRET_KEY must be at least 32 characters long.")
            lowered_secret = self.SECRET_KEY.lower()
            if "super-secret" in lowered_secret or "change-in-prod" in lowered_secret or "default" in lowered_secret:
                raise ValueError("Production SECRET_KEY cannot contain default or insecure substrings.")

            # 2. TOKEN_ENCRYPTION_KEY validation
            if not self.TOKEN_ENCRYPTION_KEY:
                raise ValueError("Production TOKEN_ENCRYPTION_KEY must be explicitly set.")
            try:
                raw_bytes = base64.urlsafe_b64decode(self.TOKEN_ENCRYPTION_KEY.encode("ascii"))
                if len(raw_bytes) != 32:
                    raise ValueError
            except Exception:
                raise ValueError("Production TOKEN_ENCRYPTION_KEY must be a valid 32-byte base64 Fernet key.")

            # 3. DATABASE_URL validation
            if self.DATABASE_URL.startswith("sqlite"):
                raise ValueError("SQLite is forbidden in production; PostgreSQL is required.")

            # 4. Redis and Rate Limiting validation
            if self.RATE_LIMIT_ENABLED:
                if not self.REDIS_URL:
                    raise ValueError("REDIS_URL must be configured when RATE_LIMIT_ENABLED is true in production.")
                if not (self.REDIS_URL.startswith("redis://") or self.REDIS_URL.startswith("rediss://")):
                    raise ValueError("REDIS_URL must begin with redis:// or rediss://.")
                if self.RATE_LIMIT_STORAGE == "memory":
                    raise ValueError("In-memory rate limiting is forbidden in production; Redis is required.")

            # 5. Google OAuth credentials validation
            if not self.GOOGLE_CLIENT_ID or not self.GOOGLE_CLIENT_SECRET:
                raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be configured in production.")

            # 6. Gemini API Key validation
            if not self.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY must be configured in production.")

            # 7. CORS validation
            origins = self.ALLOWED_ORIGINS if isinstance(self.ALLOWED_ORIGINS, list) else [self.ALLOWED_ORIGINS]
            if "*" in origins:
                raise ValueError("Wildcard CORS ('*') is forbidden in production with credentials enabled.")

            # 8. Secure Cookies validation
            if not self.SESSION_COOKIE_SECURE:
                raise ValueError("SESSION_COOKIE_SECURE must be True in production.")

            # 9. Trusted Proxy configuration
            trusted = self.TRUSTED_PROXY_IPS if isinstance(self.TRUSTED_PROXY_IPS, list) else [self.TRUSTED_PROXY_IPS]
            if not trusted or "0.0.0.0/0" in trusted:
                raise ValueError("TRUSTED_PROXY_IPS must be explicitly configured in production without broad wildcards.")

        return self

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


def _load_credentials_file_if_available(settings_obj: Settings) -> None:
    """
    Safely inspects GOOGLE_CREDENTIALS_PATH or default credentials.json locations
    and loads client_id/client_secret if not already specified.
    Never logs secret contents.
    """
    candidate_paths = []
    if settings_obj.GOOGLE_CREDENTIALS_PATH:
        candidate_paths.append(Path(settings_obj.GOOGLE_CREDENTIALS_PATH))

    # Standard candidate locations
    candidate_paths.extend([
        Path("credentials.json"),
        Path("../credentials.json"),
        Path("/home/raj/AI-ASSISTANT/credentials.json"),
        Path("backend/credentials.json"),
    ])

    for path in candidate_paths:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                client_config = data.get("web") or data.get("installed") or {}
                if not settings_obj.GOOGLE_CLIENT_ID and client_config.get("client_id"):
                    settings_obj.GOOGLE_CLIENT_ID = client_config["client_id"]
                if not settings_obj.GOOGLE_CLIENT_SECRET and client_config.get("client_secret"):
                    settings_obj.GOOGLE_CLIENT_SECRET = client_config["client_secret"]
                # If redirect_uris present and GOOGLE_REDIRECT_URI has default, align with first registered URI
                redirect_uris = client_config.get("redirect_uris", [])
                if redirect_uris and settings_obj.GOOGLE_REDIRECT_URI == "http://localhost:8000/auth/callback":
                    settings_obj.GOOGLE_REDIRECT_URI = redirect_uris[0]
                break
            except Exception:
                # Silently ignore parsing errors to prevent crashing or log leakage
                pass


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    s = Settings()
    _load_credentials_file_if_available(s)
    return s


settings = get_settings()
