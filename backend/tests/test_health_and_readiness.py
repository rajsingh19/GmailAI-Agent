"""
Unit and integration tests for Milestone 9 Health (Liveness) and Readiness Probes.
Verifies internal dependency checks and strict independence from external Google/Gemini APIs.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

from app.core.config import settings
from app.core.rate_limit import BaseRateLimiter, RateLimitResult, set_rate_limiter_for_testing


@pytest.mark.asyncio
async def test_health_liveness_returns_200(async_client: AsyncClient):
    """GET /health returns HTTP 200 without requiring database query."""
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == settings.PROJECT_NAME


@pytest.mark.asyncio
async def test_health_response_schema_fields(async_client: AsyncClient):
    """GET /health returns version, environment, and ISO timestamp."""
    resp = await async_client.get("/health")
    data = resp.json()
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_ready_probe_returns_200_when_database_up(async_client: AsyncClient):
    """GET /ready returns 200 and ready status when database is reachable."""
    resp = await async_client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert "database" in data["components"]
    assert data["components"]["database"]["status"] == "up"


@pytest.mark.asyncio
async def test_ready_probe_checks_database_component(async_client: AsyncClient):
    """GET /ready database component includes latency_ms measurement."""
    resp = await async_client.get("/ready")
    data = resp.json()
    db_comp = data["components"]["database"]
    assert db_comp["latency_ms"] is not None
    assert db_comp["latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_ready_probe_reports_unready_503_when_database_fails(async_client: AsyncClient):
    """When PostgreSQL is down, GET /ready returns HTTP 503 and status=unready."""
    from app.main import app
    from app.db.session import get_db

    async def fail_db():
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Connection to host db.internal:5432 refused")
        yield mock_session

    orig_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = fail_db
    try:
        resp = await async_client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unready"
        assert data["components"]["database"]["status"] == "down"
    finally:
        if orig_override:
            app.dependency_overrides[get_db] = orig_override
        else:
            del app.dependency_overrides[get_db]


@pytest.mark.asyncio
async def test_ready_probe_sanitizes_database_error(async_client: AsyncClient):
    """Database probe error message must not leak internal credentials or hosts."""
    from app.main import app
    from app.db.session import get_db

    async def fail_db():
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("password=secret123 failed for postgres://usr@db.prod:5432")
        yield mock_session

    orig_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = fail_db
    try:
        resp = await async_client.get("/ready")
        data = resp.json()
        db_err = data["components"]["database"]["error"]
        assert "password" not in db_err
        assert "secret123" not in db_err
        assert db_err == "Database connection failed"
    finally:
        if orig_override:
            app.dependency_overrides[get_db] = orig_override
        else:
            del app.dependency_overrides[get_db]


@pytest.mark.asyncio
async def test_ready_probe_checks_redis_component_when_redis_storage_enabled(async_client: AsyncClient):
    """When Redis storage is configured, /ready verifies Redis liveness."""
    orig_storage = settings.RATE_LIMIT_STORAGE
    orig_enabled = settings.RATE_LIMIT_ENABLED
    try:
        settings.RATE_LIMIT_ENABLED = True
        settings.RATE_LIMIT_STORAGE = "redis"

        mock_limiter = AsyncMock(spec=BaseRateLimiter)
        mock_limiter.ping.return_value = True
        set_rate_limiter_for_testing(mock_limiter)

        resp = await async_client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "redis" in data["components"]
        assert data["components"]["redis"]["status"] == "up"
    finally:
        set_rate_limiter_for_testing(None)
        settings.RATE_LIMIT_STORAGE = orig_storage
        settings.RATE_LIMIT_ENABLED = orig_enabled


@pytest.mark.asyncio
async def test_ready_probe_skips_redis_when_memory_storage_enabled(async_client: AsyncClient):
    """When in-memory rate limiting is used, Redis probe is marked skipped."""
    orig_storage = settings.RATE_LIMIT_STORAGE
    orig_enabled = settings.RATE_LIMIT_ENABLED
    try:
        settings.RATE_LIMIT_ENABLED = True
        settings.RATE_LIMIT_STORAGE = "memory"
        resp = await async_client.get("/ready")
        data = resp.json()
        assert data["components"]["redis"]["status"] == "skipped"
    finally:
        settings.RATE_LIMIT_STORAGE = orig_storage
        settings.RATE_LIMIT_ENABLED = orig_enabled


@pytest.mark.asyncio
async def test_ready_probe_does_not_call_google_apis(async_client: AsyncClient):
    """
    CRITICAL ARCHITECTURAL TEST:
    /ready MUST NOT make outgoing requests to Google Gmail or Calendar APIs.
    """
    with patch("app.services.gmail_service.build") as mock_gmail, \
         patch("app.services.calendar_service.build") as mock_cal:
        resp = await async_client.get("/ready")
        assert resp.status_code == 200
        mock_gmail.assert_not_called()
        mock_cal.assert_not_called()


@pytest.mark.asyncio
async def test_ready_probe_does_not_call_gemini(async_client: AsyncClient):
    """
    CRITICAL ARCHITECTURAL TEST:
    /ready MUST NOT make outgoing requests to Google Gemini LLM or embedding endpoints.
    """
    with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response") as mock_gen, \
         patch("app.ai.embeddings.gemini_embeddings.GeminiEmbeddingProvider.embed_text") as mock_embed:
        resp = await async_client.get("/ready")
        assert resp.status_code == 200
        mock_gen.assert_not_called()
        mock_embed.assert_not_called()
