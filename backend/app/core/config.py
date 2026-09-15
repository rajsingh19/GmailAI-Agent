import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Personal AI Assistant"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

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

    # Security & Session Configuration
    SECRET_KEY: str = "super-secret-session-signing-key-minimum-32-chars-change-in-prod"
    TOKEN_ENCRYPTION_KEY: str = ""  # Base64 Fernet key, auto-derived in dev if empty
    SESSION_COOKIE_NAME: str = "ai_assistant_session"
    SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 7  # 7 days
    STATE_COOKIE_NAME: str = "oauth_state_csrf"
    STATE_COOKIE_MAX_AGE: int = 600  # 10 minutes

    # Database Configuration (SQLite default with PostgreSQL support)
    DATABASE_URL: str = "sqlite+aiosqlite:///./ai_assistant.db"

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
    AI_MODEL_NAME: str = "gemini-2.0-flash"
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
    CONFIRMATION_TOKEN_TTL_SECONDS: int = 300  # 5 minutes

    @property
    def effective_model_name(self) -> str:
        """Returns the configured model name, prioritizing GEMINI_MODEL over AI_MODEL_NAME."""
        return self.GEMINI_MODEL or self.AI_MODEL_NAME

    @property
    def effective_embedding_model(self) -> str:
        """Returns the configured embedding model name."""
        return self.EMBEDDING_MODEL

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
