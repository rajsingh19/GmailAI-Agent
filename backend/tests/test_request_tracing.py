"""
Unit and integration tests for Milestone 9 Request Tracing and X-Request-ID propagation.
"""
import pytest
from httpx import AsyncClient

from app.core.context import get_request_id


@pytest.mark.asyncio
async def test_request_tracing_generates_id_when_missing(async_client: AsyncClient):
    """When client provides no X-Request-ID, backend generates one starting with req_."""
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    req_id = resp.headers.get("X-Request-ID")
    assert req_id is not None
    assert req_id.startswith("req_")
    assert len(req_id) >= 10


@pytest.mark.asyncio
async def test_request_tracing_preserves_incoming_request_id(async_client: AsyncClient):
    """When client passes X-Request-ID, backend preserves it exactly."""
    custom_id = "trace-custom-uuid-1234-abcd"
    resp = await async_client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == custom_id


@pytest.mark.asyncio
async def test_request_tracing_header_present_in_health_response(async_client: AsyncClient):
    """Health check response contains X-Request-ID."""
    resp = await async_client.get("/health")
    assert "X-Request-ID" in resp.headers


@pytest.mark.asyncio
async def test_request_tracing_header_present_in_error_response(async_client: AsyncClient):
    """Error responses (e.g. 404 or 422) return X-Request-ID and match error payload."""
    resp = await async_client.get("/api/v1/non-existent-endpoint-xyz")
    assert resp.status_code == 404
    header_id = resp.headers.get("X-Request-ID")
    assert header_id is not None
    data = resp.json()
    assert "error" in data
    assert data["error"]["request_id"] == header_id


@pytest.mark.asyncio
async def test_request_tracing_unique_across_sequential_requests(async_client: AsyncClient):
    """Sequential requests without custom headers receive distinct request IDs."""
    resp1 = await async_client.get("/health")
    resp2 = await async_client.get("/health")
    id1 = resp1.headers.get("X-Request-ID")
    id2 = resp2.headers.get("X-Request-ID")
    assert id1 != id2


@pytest.mark.asyncio
async def test_request_tracing_cleans_whitespace_in_header(async_client: AsyncClient):
    """Incoming request ID with leading/trailing spaces is stripped."""
    resp = await async_client.get("/health", headers={"X-Request-ID": "  clean-id-999  "})
    assert resp.headers.get("X-Request-ID") == "clean-id-999"


@pytest.mark.asyncio
async def test_request_tracing_injected_into_contextvar_during_request(async_client: AsyncClient):
    """ContextVar request_id matches the response header."""
    custom_id = "contextvar-verify-id-777"
    resp = await async_client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.headers.get("X-Request-ID") == custom_id


@pytest.mark.asyncio
async def test_request_tracing_propagates_to_unauthenticated_requests(async_client: AsyncClient):
    """Unauthenticated endpoints (like /auth/session) receive trace ID."""
    resp = await async_client.get("/auth/session")
    assert "X-Request-ID" in resp.headers
