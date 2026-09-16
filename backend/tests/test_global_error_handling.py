"""
Unit and integration tests for Milestone 9 Global Error Handling and Zero-Leakage Invariants.
Verifies that error payloads match {error: {code, message, request_id}} and never leak
SQL syntax, stack traces, credentials, or file paths.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError

from app.core.errors import (
    AppException,
    RateLimitExceededError,
    make_error_response,
)


def test_standard_error_format_keys():
    """make_error_response returns exactly the standardized M9 JSON structure."""
    resp = make_error_response(
        code="TEST_ERROR",
        message="A test error occurred",
        status_code=400,
        request_id="req_test_123",
    )
    import json
    data = json.loads(resp.body)
    assert "error" in data
    err = data["error"]
    assert err["code"] == "TEST_ERROR"
    assert err["message"] == "A test error occurred"
    assert err["request_id"] == "req_test_123"
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_validation_error_returns_422_with_safe_fields(async_client: AsyncClient):
    """Validation errors return HTTP 422 with structured field paths and no stack trace."""
    from pydantic import BaseModel, Field
    from app.main import app

    class TestPayload(BaseModel):
        required_title: str
        required_count: int

    @app.post("/api/v1/test-validation-endpoint")
    async def sample_endpoint(payload: TestPayload):
        return {"status": "ok"}

    resp = await async_client.post("/api/v1/test-validation-endpoint", json={"required_title": 123})
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "request_id" in data["error"]
    assert "Traceback" not in resp.text
    assert "details" in data["error"]


@pytest.mark.asyncio
async def test_not_found_returns_404_standard_error(async_client: AsyncClient):
    """404 Not Found returns standardized error."""
    resp = await async_client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_unauthorized_returns_401_standard_error(async_client: AsyncClient):
    """Protected endpoints accessed without auth return HTTP 401 standard error."""
    resp = await async_client.get("/api/v1/tasks")
    assert resp.status_code == 401
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_database_error_returns_500_with_zero_sql_leakage(async_client: AsyncClient, monkeypatch):
    """
    CRITICAL SECURITY TEST:
    Database exceptions return safe 500 without leaking raw SQL, table names, or credentials.
    """
    from app.main import app

    @app.get("/api/v1/test-db-error-trigger")
    async def trigger_db_error():
        raise OperationalError("SELECT * FROM users WHERE password_hash = 'xyz'", {}, Exception("DB down"))

    resp = await async_client.get("/api/v1/test-db-error-trigger")
    assert resp.status_code == 500
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "DATABASE_ERROR"
    assert "Database service temporarily unavailable" in data["error"]["message"]
    # Verify zero SQL leaked to client
    assert "SELECT" not in resp.text
    assert "password_hash" not in resp.text


@pytest.mark.asyncio
async def test_unhandled_exception_returns_500_with_zero_traceback_leakage(async_client: AsyncClient):
    """
    CRITICAL SECURITY TEST:
    Unhandled exceptions return safe 500 without leaking file paths or Python tracebacks.
    """
    from app.main import app

    @app.get("/api/v1/test-unhandled-crash")
    async def trigger_crash():
        raise RuntimeError("Internal secret computation failed in /var/app/secret.py")

    resp = await async_client.get("/api/v1/test-unhandled-crash")
    assert resp.status_code == 500
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "Traceback" not in resp.text
    assert "/var/app/secret.py" not in resp.text


def test_rate_limit_error_returns_429_with_retry_after():
    """RateLimitExceededError generates HTTP 429 and carries retry_after."""
    exc = RateLimitExceededError("Rate limit exceeded", retry_after=45)
    assert exc.status_code == 429
    assert exc.code == "RATE_LIMIT_EXCEEDED"
    assert exc.retry_after == 45
    assert exc.details["retry_after"] == 45


@pytest.mark.asyncio
async def test_error_response_contains_x_request_id_header(async_client: AsyncClient):
    """Error responses must contain X-Request-ID header matching the payload."""
    resp = await async_client.get("/api/v1/unknown-route")
    assert "X-Request-ID" in resp.headers
    data = resp.json()
    assert data["error"]["request_id"] == resp.headers["X-Request-ID"]


def test_error_details_field_omitted_when_none():
    """Details key is omitted when details is None to keep payload minimal."""
    resp = make_error_response("CODE", "Msg", 400, details=None)
    import json
    data = json.loads(resp.body)
    assert "details" not in data["error"]


def test_error_details_field_included_when_provided():
    """Details key is included when provided."""
    resp = make_error_response("CODE", "Msg", 400, details={"info": "additional context"})
    import json
    data = json.loads(resp.body)
    assert "details" in data["error"]
    assert data["error"]["details"]["info"] == "additional context"
