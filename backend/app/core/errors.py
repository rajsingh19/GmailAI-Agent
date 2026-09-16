"""
Standardized error structures and exception types for Milestone 9.
Never exposes internal database errors, stack traces, credentials, or file paths.
"""
from typing import Any, Dict, Optional
from fastapi import status
from fastapi.responses import JSONResponse

from app.core.context import get_request_id


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class RateLimitExceededError(AppException):
    """Raised when an endpoint exceeds its rate limit."""

    def __init__(
        self,
        message: str = "Too many requests. Please retry later.",
        retry_after: int = 60,
    ):
        super().__init__(
            code="RATE_LIMIT_EXCEEDED",
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after


class ServiceUnavailableError(AppException):
    """Raised when an internal or external dependency is unavailable."""

    def __init__(self, message: str = "Service temporarily unavailable. Please retry later."):
        super().__init__(
            code="SERVICE_UNAVAILABLE",
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def make_error_response(
    code: str,
    message: str,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    details: Optional[Any] = None,
    request_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """
    Constructs a standardized M9 JSON error response:
    {
        "error": {
            "code": "...",
            "message": "...",
            "request_id": "...",
            "details": ... (optional)
        }
    }
    """
    req_id = request_id or get_request_id() or "unknown"
    error_content: Dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": req_id,
    }
    if details is not None:
        error_content["details"] = details

    response_headers = headers or {}
    response_headers["X-Request-ID"] = req_id

    content = {
        "error": error_content,
        "detail": message,
    }

    return JSONResponse(
        status_code=status_code,
        content=content,
        headers=response_headers,
    )
