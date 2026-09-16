"""
Tests for security headers and environment-aware Content-Security-Policy (CSP).
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_security_headers_present():
    """Verifies baseline hardening headers are present on all responses."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "geolocation=()" in resp.headers.get("Permissions-Policy", "")


@pytest.mark.asyncio
async def test_x_frame_options_deny():
    """Verifies clickjacking protections: X-Frame-Options is DENY."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"


@pytest.mark.asyncio
async def test_x_content_type_options_nosniff():
    """Verifies MIME-type sniffing is blocked."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.asyncio
async def test_permissions_policy_disables_sensitive_apis():
    """Verifies camera, microphone, and geolocation are disabled in Permissions-Policy."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        policy = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in policy
        assert "microphone=()" in policy
        assert "geolocation=()" in policy


@pytest.mark.asyncio
async def test_csp_development_profile(monkeypatch):
    """Verifies development CSP permits localhost dev tools and ports."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "localhost:5173" in csp
        assert "unsafe-eval" in csp
        assert "frame-ancestors 'none'" in csp


@pytest.mark.asyncio
async def test_csp_production_profile(monkeypatch):
    """Verifies production CSP strips localhost origins and unsafe-eval."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "localhost" not in csp
        assert "unsafe-eval" not in csp
        assert "frame-ancestors 'none'" in csp
        assert "default-src 'self'" in csp


@pytest.mark.asyncio
async def test_csp_report_only_toggle(monkeypatch):
    """Verifies CSP_REPORT_ONLY toggles Content-Security-Policy-Report-Only header."""
    monkeypatch.setattr(settings, "CSP_REPORT_ONLY", True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert "Content-Security-Policy-Report-Only" in resp.headers
        assert "Content-Security-Policy" not in resp.headers


@pytest.mark.asyncio
async def test_csp_allows_google_profile_images_and_fonts(monkeypatch):
    """Verifies CSP allows Google profile avatars and fonts in both dev and prod."""
    for env in ["development", "production"]:
        monkeypatch.setattr(settings, "ENVIRONMENT", env)
        monkeypatch.setattr(settings, "CSP_REPORT_ONLY", False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/health")
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "https://lh3.googleusercontent.com" in csp
            assert "https://fonts.googleapis.com" in csp
            assert "https://fonts.gstatic.com" in csp
