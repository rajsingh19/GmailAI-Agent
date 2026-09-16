"""
Tests for /metrics endpoint access control and authentication defense.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_metrics_accessible_when_no_token_configured(monkeypatch):
    """When METRICS_SECRET_TOKEN is not configured, /metrics is accessible."""
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_SECRET_TOKEN", None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_forbidden_without_token_when_configured(monkeypatch):
    """When METRICS_SECRET_TOKEN is set, unauthenticated calls receive 403."""
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_SECRET_TOKEN", "secure-prometheus-pass-123")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
        assert resp.status_code == 403
        data = resp.json()
        assert data["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_metrics_forbidden_with_wrong_token(monkeypatch):
    """When provided token does not match, request is rejected with 403."""
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_SECRET_TOKEN", "secure-prometheus-pass-123")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/metrics",
            headers={"X-Metrics-Token": "invalid-token"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_metrics_allowed_with_valid_x_metrics_token(monkeypatch):
    """When valid X-Metrics-Token is provided, 200 OK is returned."""
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_SECRET_TOKEN", "secure-prometheus-pass-123")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/metrics",
            headers={"X-Metrics-Token": "secure-prometheus-pass-123"},
        )
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_allowed_with_bearer_token(monkeypatch):
    """When valid Bearer token is provided in Authorization header, 200 OK is returned."""
    monkeypatch.setattr(settings, "METRICS_ENABLED", True)
    monkeypatch.setattr(settings, "METRICS_SECRET_TOKEN", "secure-prometheus-pass-123")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/metrics",
            headers={"Authorization": "Bearer secure-prometheus-pass-123"},
        )
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_404_when_metrics_disabled(monkeypatch):
    """When METRICS_ENABLED=False, /metrics returns 404."""
    monkeypatch.setattr(settings, "METRICS_ENABLED", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"
