"""
Request context management using Python contextvars.
Thread-safe and coroutine-safe tracking for request_id and user_id.
"""
import contextvars
from typing import Optional

request_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)
user_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "user_id", default=None
)


def get_request_id() -> Optional[str]:
    """Retrieve current request ID from context."""
    return request_id_ctx.get()


def set_request_id(req_id: str) -> None:
    """Set current request ID in context."""
    request_id_ctx.set(req_id)


def get_user_id() -> Optional[str]:
    """Retrieve current authenticated user ID from context."""
    return user_id_ctx.get()


def set_user_id(uid: str) -> None:
    """Set current authenticated user ID in context."""
    user_id_ctx.set(uid)
