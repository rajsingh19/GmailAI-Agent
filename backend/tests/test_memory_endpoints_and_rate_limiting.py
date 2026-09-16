"""
Tests for Memory REST Endpoints & Redis Rate Limiting (Milestone 11).
Contains exactly 10 tests verifying:
- Unauthenticated requests to /api/v1/memories return 401
- GET /api/v1/memories returns paginated memory list
- POST /api/v1/memories creates new memory
- POST /api/v1/memories rejects detected secret with 400
- GET /api/v1/memories/search searches memories with query parameter
- GET /api/v1/memories/stats returns category and confidence metrics
- PATCH /api/v1/memories/{id} updates memory value
- POST /api/v1/memories/{id}/deactivate marks memory inactive
- DELETE /api/v1/memories/{id} deletes memory returning 204
- Redis sliding-window rate limiting on /api/v1/memories returns 429 when quota exceeded
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.schemas.memory import MemoryCreateRequest
from app.services.memory_service import MemoryService
from app.core.security import SecurityManager
from app.core.config import settings
from app.core.rate_limit import InMemoryRateLimiter, set_rate_limiter_for_testing


@pytest.fixture
async def api_user(test_db: AsyncSession) -> User:
    user = User(id="user_api_mem_1", email="api_mem@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


@pytest.fixture
def auth_client(async_client: AsyncClient, api_user: User) -> AsyncClient:
    token = SecurityManager.create_session_token(api_user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)
    return async_client


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(async_client: AsyncClient):
    """1. Test unauthenticated request to /api/v1/memories returns 401."""
    async_client.cookies.clear()
    resp = await async_client.get("/api/v1/memories")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_memories_list_endpoint(auth_client: AsyncClient, test_db: AsyncSession, api_user: User):
    """2. Test GET /api/v1/memories returns list of memories."""
    await MemoryService.create_or_upsert_memory(
        test_db, api_user.id,
        MemoryCreateRequest(category="user_preference", key="endpoint.k1", value="v1", source="user_ui")
    )
    resp = await auth_client.get("/api/v1/memories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total"] >= 1
    assert any(m["key"] == "endpoint.k1" for m in data["items"])


@pytest.mark.asyncio
async def test_post_create_memory_endpoint(auth_client: AsyncClient, api_user: User):
    """3. Test POST /api/v1/memories creates new memory with 201 Created."""
    payload = {
        "category": "user_preference",
        "key": "endpoint.post",
        "value": "Docker with Compose",
        "description": "Dev environment setup",
    }
    resp = await auth_client.post("/api/v1/memories", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["key"] == "endpoint.post"
    assert data["value"] == "Docker with Compose"
    assert data["confidence"] == "EXPLICIT"


@pytest.mark.asyncio
async def test_post_memory_with_secret_rejected_with_400(auth_client: AsyncClient, api_user: User):
    """4. Test POST /api/v1/memories with secret returns 400 Bad Request."""
    payload = {
        "category": "user_fact",
        "key": "aws.secret",
        "value": "Key is AKIAIOSFODNN7EXAMPLE",
    }
    resp = await auth_client.post("/api/v1/memories", json=payload)
    assert resp.status_code == 400
    assert "credentials" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_search_memories_endpoint(auth_client: AsyncClient, test_db: AsyncSession, api_user: User):
    """5. Test GET /api/v1/memories/search endpoint."""
    await MemoryService.create_or_upsert_memory(
        test_db, api_user.id,
        MemoryCreateRequest(category="project_context", key="search.target", value="SearchTargetValue", source="user_ui")
    )
    resp = await auth_client.get("/api/v1/memories/search?query=SearchTargetValue")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["results"]) >= 1
    assert data["results"][0]["key"] == "search.target"


@pytest.mark.asyncio
async def test_get_memory_stats_endpoint(auth_client: AsyncClient, test_db: AsyncSession, api_user: User):
    """6. Test GET /api/v1/memories/stats endpoint."""
    await MemoryService.create_or_upsert_memory(
        test_db, api_user.id,
        MemoryCreateRequest(category="workflow_preference", key="wf.ci", value="GitHub Actions", source="user_ui")
    )
    resp = await auth_client.get("/api/v1/memories/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_memories" in data
    assert "active_memories" in data
    assert "by_category" in data


@pytest.mark.asyncio
async def test_patch_memory_endpoint(auth_client: AsyncClient, test_db: AsyncSession, api_user: User):
    """7. Test PATCH /api/v1/memories/{id} updates memory."""
    mem = await MemoryService.create_or_upsert_memory(
        test_db, api_user.id,
        MemoryCreateRequest(category="user_preference", key="patch.me", value="OldVal", source="user_ui")
    )
    resp = await auth_client.patch(f"/api/v1/memories/{mem.id}", json={"value": "NewVal"})
    assert resp.status_code == 200
    assert resp.json()["value"] == "NewVal"


@pytest.mark.asyncio
async def test_deactivate_memory_endpoint(auth_client: AsyncClient, test_db: AsyncSession, api_user: User):
    """8. Test POST /api/v1/memories/{id}/deactivate marks memory inactive."""
    mem = await MemoryService.create_or_upsert_memory(
        test_db, api_user.id,
        MemoryCreateRequest(category="user_preference", key="deact.me", value="DeactVal", source="user_ui")
    )
    resp = await auth_client.post(f"/api/v1/memories/{mem.id}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["active"] is False


@pytest.mark.asyncio
async def test_delete_memory_endpoint(auth_client: AsyncClient, test_db: AsyncSession, api_user: User):
    """9. Test DELETE /api/v1/memories/{id} deletes memory with 204 No Content."""
    mem = await MemoryService.create_or_upsert_memory(
        test_db, api_user.id,
        MemoryCreateRequest(category="user_preference", key="delete.me", value="DelVal", source="user_ui")
    )
    resp = await auth_client.delete(f"/api/v1/memories/{mem.id}")
    assert resp.status_code == 204

    # Verify not found on subsequent get
    check_resp = await auth_client.get(f"/api/v1/memories/{mem.id}")
    assert check_resp.status_code == 404


@pytest.mark.asyncio
async def test_rate_limiting_on_memory_endpoints(auth_client: AsyncClient, api_user: User):
    """10. Test rate limiting on /api/v1/memories returns HTTP 429 when quota exceeded."""
    limiter = InMemoryRateLimiter()
    set_rate_limiter_for_testing(limiter)
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_MEMORY_LIMIT = 3
    settings.RATE_LIMIT_MEMORY_WINDOW = 60

    try:
        # First 3 requests succeed
        for _ in range(3):
            r = await auth_client.get("/api/v1/memories")
            assert r.status_code == 200

        # 4th request exceeds quota -> HTTP 429
        r4 = await auth_client.get("/api/v1/memories")
        assert r4.status_code == 429
        assert "Retry-After" in r4.headers
        assert "X-RateLimit-Limit" in r4.headers
    finally:
        settings.RATE_LIMIT_ENABLED = False
        set_rate_limiter_for_testing(None)
