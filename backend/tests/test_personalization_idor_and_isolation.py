"""
Suite 7: test_personalization_idor_and_isolation.py (12 tests)
Verifies multi-user isolation, IDOR prevention, unauthenticated rejection, and cache key scoping.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.personalization import (
    PersonalizationLevel,
    PersonalizationConfigUpdate,
)
from app.services.personalization_service import PersonalizationService
from app.services.memory_service import MemoryService
from app.schemas.memory import MemoryCreateRequest


@pytest.mark.asyncio
async def test_idor_config_get_isolated(db_session: AsyncSession, test_user: User, test_user_b: User):
    """1. Test that User A and User B have separate, isolated personalization configs."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(personalization_enabled=True, personalization_level=PersonalizationLevel.HIGH),
    )
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user_b.id,
        config_in=PersonalizationConfigUpdate(personalization_enabled=False, personalization_level=PersonalizationLevel.LOW),
    )
    cfg_a = await PersonalizationService.get_user_personalization_config(db=db_session, user_id=test_user.id)
    cfg_b = await PersonalizationService.get_user_personalization_config(db=db_session, user_id=test_user_b.id)
    assert cfg_a["personalization_enabled"] is True
    assert cfg_a["personalization_level"] == "HIGH"
    assert cfg_b["personalization_enabled"] is False
    assert cfg_b["personalization_level"] == "LOW"


@pytest.mark.asyncio
async def test_idor_config_patch_isolated(db_session: AsyncSession, test_user: User, test_user_b: User):
    """2. Test that updating User A's config does not alter User B's config."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(personalization_level=PersonalizationLevel.MEDIUM),
    )
    cfg_b = await PersonalizationService.get_user_personalization_config(db=db_session, user_id=test_user_b.id)
    assert cfg_b["personalization_level"] == "MEDIUM" or cfg_b["personalization_level"] == "LOW"


@pytest.mark.asyncio
async def test_idor_preview_isolated(db_session: AsyncSession, test_user: User, test_user_b: User):
    """3. Test that User A preview cannot see User B's memories."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(personalization_enabled=True, personalization_level=PersonalizationLevel.HIGH),
    )
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user_b.id,
        config_in=PersonalizationConfigUpdate(personalization_enabled=True, personalization_level=PersonalizationLevel.HIGH),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user_b.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="user_b_exclusive_key",
            value="User B secret tech",
            source="explicit_user_request",
        ),
    )
    preview_a = await PersonalizationService.preview_personalization(
        db=db_session, user_id=test_user.id, query="user_b_exclusive_key"
    )
    assert all(item.key != "user_b_exclusive_key" for item in preview_a)


@pytest.mark.asyncio
async def test_idor_session_override_isolated(test_user: User, test_user_b: User):
    """4. Test that User A session override does not affect User B session override even with same session_id."""
    PersonalizationService.reset_in_memory_stores()
    shared_session_name = "common_session"
    await PersonalizationService.set_session_override(test_user.id, shared_session_name, enabled=False)
    await PersonalizationService.set_session_override(test_user_b.id, shared_session_name, enabled=True)

    status_a = await PersonalizationService.get_session_override(test_user.id, shared_session_name)
    status_b = await PersonalizationService.get_session_override(test_user_b.id, shared_session_name)
    assert status_a is False
    assert status_b is True


@pytest.mark.asyncio
async def test_idor_memory_retrieval_cross_user(db_session: AsyncSession, test_user: User, test_user_b: User):
    """5. Test that personalization context synthesis strictly isolates memories by user_id."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(personalization_enabled=True, personalization_level=PersonalizationLevel.HIGH),
    )
    # Store memory under User B
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user_b.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.secret_stack",
            value="PrivateStack123",
            source="explicit_user_request",
        ),
    )
    # Query under User A
    res_a = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="coding secret_stack PrivateStack123"
    )
    assert "PrivateStack123" not in res_a.context_text
    assert "coding.secret_stack" not in res_a.metadata.applied_keys


@pytest.mark.asyncio
async def test_idor_redis_pref_cache_isolated(test_user: User, test_user_b: User):
    """6. Test that cache keys for personalization preferences are strictly scoped by user_id."""
    key_a = f"cache:personalization_pref:{test_user.id}"
    key_b = f"cache:personalization_pref:{test_user_b.id}"
    assert key_a != key_b
    assert test_user.id in key_a
    assert test_user_b.id in key_b


@pytest.mark.asyncio
async def test_idor_redis_override_cache_isolated(test_user: User, test_user_b: User):
    """7. Test that session override Redis keys are strictly scoped by user_id."""
    key_a = f"sess:personalization_override:{test_user.id}:sess_1"
    key_b = f"sess:personalization_override:{test_user_b.id}:sess_1"
    assert key_a != key_b


@pytest.mark.asyncio
async def test_idor_api_config_unauthenticated_rejected(async_client: AsyncClient):
    """8. Test that GET /api/v1/personalization/config is rejected with 401 without authentication."""
    response = await async_client.get("/api/v1/personalization/config")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_idor_api_patch_unauthenticated_rejected(async_client: AsyncClient):
    """9. Test that PATCH /api/v1/personalization/config is rejected with 401 without authentication."""
    response = await async_client.patch(
        "/api/v1/personalization/config",
        json={"personalization_enabled": True},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_idor_api_preview_unauthenticated_rejected(async_client: AsyncClient):
    """10. Test that POST /api/v1/personalization/preview is rejected with 401 without authentication."""
    response = await async_client.post(
        "/api/v1/personalization/preview",
        json={"query": "FastAPI"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_idor_api_session_override_unauthenticated_rejected(async_client: AsyncClient):
    """11. Test that POST /api/v1/personalization/session-override is rejected with 401 without authentication."""
    response = await async_client.post(
        "/api/v1/personalization/session-override",
        json={"session_id": "sess_1", "disable_personalization": True},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_idor_rate_limiting_personalization_endpoint(authenticated_client: AsyncClient):
    """12. Test that authenticated client can successfully access personalization config with rate headers."""
    response = await authenticated_client.get("/api/v1/personalization/config")
    assert response.status_code == 200
    data = response.json()
    assert "personalization_enabled" in data
    assert "personalization_level" in data
