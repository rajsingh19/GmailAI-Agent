"""
Tests for Multi-User Isolation & Anti-IDOR Security (Milestone 11).
Contains exactly 12 tests verifying:
- User A cannot get User B memory via Service
- User A cannot update User B memory via Service
- User A cannot deactivate User B memory via Service
- User A cannot delete User B memory via Service
- User A list query returns zero User B memories
- User A search query returns zero User B memories
- User A agent context returns zero User B memories
- REST GET /memories/{id} returns 404 for another user's memory (zero leakage)
- REST PATCH /memories/{id} returns 404 for another user's memory
- REST POST /memories/{id}/deactivate returns 404 for another user's memory
- REST DELETE /memories/{id} returns 404 for another user's memory
- Same category and key can coexist independently for User A and User B
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.schemas.memory import MemoryCreateRequest, MemoryUpdateRequest
from app.services.memory_service import MemoryService
from app.core.security import SecurityManager
from app.core.config import settings


@pytest.fixture
async def user_a(test_db: AsyncSession) -> User:
    user = User(id="user_idor_a", email="user_a@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


@pytest.fixture
async def user_b(test_db: AsyncSession) -> User:
    user = User(id="user_idor_b", email="user_b@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


@pytest.mark.asyncio
async def test_user_a_cannot_get_user_b_memory(test_db: AsyncSession, user_a: User, user_b: User):
    """1. Test User A cannot retrieve User B's memory via service layer."""
    req_b = MemoryCreateRequest(category="user_preference", key="lang", value="Kotlin", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    retrieved = await MemoryService.get_memory(test_db, user_a.id, mem_b.id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_user_a_cannot_update_user_b_memory(test_db: AsyncSession, user_a: User, user_b: User):
    """2. Test User A cannot update User B's memory."""
    req_b = MemoryCreateRequest(category="user_preference", key="lang", value="Scala", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    update_in = MemoryUpdateRequest(value="HackedValue")
    updated = await MemoryService.update_memory(test_db, user_a.id, mem_b.id, update_in)
    assert updated is None

    # Verify B's memory unchanged
    mem_b_check = await MemoryService.get_memory(test_db, user_b.id, mem_b.id)
    assert mem_b_check.value == "Scala"


@pytest.mark.asyncio
async def test_user_a_cannot_deactivate_user_b_memory(test_db: AsyncSession, user_a: User, user_b: User):
    """3. Test User A cannot deactivate User B's memory."""
    req_b = MemoryCreateRequest(category="user_preference", key="editor", value="Emacs", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    deactivated = await MemoryService.deactivate_memory(test_db, user_a.id, mem_b.id)
    assert deactivated is None

    mem_b_check = await MemoryService.get_memory(test_db, user_b.id, mem_b.id)
    assert mem_b_check.active is True


@pytest.mark.asyncio
async def test_user_a_cannot_delete_user_b_memory(test_db: AsyncSession, user_a: User, user_b: User):
    """4. Test User A cannot delete User B's memory."""
    req_b = MemoryCreateRequest(category="user_preference", key="cloud", value="GCP", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    deleted = await MemoryService.delete_memory(test_db, user_a.id, mem_b.id)
    assert deleted is False

    mem_b_check = await MemoryService.get_memory(test_db, user_b.id, mem_b.id)
    assert mem_b_check is not None


@pytest.mark.asyncio
async def test_user_a_list_memories_excludes_user_b(test_db: AsyncSession, user_a: User, user_b: User):
    """5. Test list_memories only returns memories for authenticated user."""
    req_a = MemoryCreateRequest(category="user_preference", key="lang.a", value="Python", source="user_ui")
    req_b = MemoryCreateRequest(category="user_preference", key="lang.b", value="C++", source="user_ui")
    await MemoryService.create_or_upsert_memory(test_db, user_a.id, req_a)
    await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    items_a, total_a = await MemoryService.list_memories(test_db, user_a.id)
    assert all(m.user_id == user_a.id for m in items_a)
    assert not any(m.key == "lang.b" for m in items_a)


@pytest.mark.asyncio
async def test_user_a_search_memories_excludes_user_b(test_db: AsyncSession, user_a: User, user_b: User):
    """6. Test search_memories never searches or leaks User B's memories."""
    req_b = MemoryCreateRequest(category="user_fact", key="secret.project", value="ProjectZeusSecret", source="user_ui")
    await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    results_a = await MemoryService.search_memories(test_db, user_a.id, query="ProjectZeusSecret")
    assert results_a == []


@pytest.mark.asyncio
async def test_user_a_agent_context_excludes_user_b(test_db: AsyncSession, user_a: User, user_b: User):
    """7. Test get_relevant_memory_context isolates user memories in agent turn."""
    req_b = MemoryCreateRequest(category="user_preference", key="coding.style", value="FunctionalProgramming", source="user_ui")
    await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    ctx_a = await MemoryService.get_relevant_memory_context(test_db, user_a.id, query="FunctionalProgramming")
    assert ctx_a == []


@pytest.mark.asyncio
async def test_rest_get_memory_returns_404_on_idor(async_client: AsyncClient, test_db: AsyncSession, user_a: User, user_b: User):
    """8. Test REST GET /api/v1/memories/{id} returns 404 for another user's memory."""
    req_b = MemoryCreateRequest(category="user_fact", key="b.fact", value="B Fact", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    # Login as User A
    session_token = SecurityManager.create_session_token(user_a.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_token)

    response = await async_client.get(f"/api/v1/memories/{mem_b.id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_rest_patch_memory_returns_404_on_idor(async_client: AsyncClient, test_db: AsyncSession, user_a: User, user_b: User):
    """9. Test REST PATCH /api/v1/memories/{id} returns 404 on IDOR attempt."""
    req_b = MemoryCreateRequest(category="user_fact", key="b.patch", value="B Original", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    session_token = SecurityManager.create_session_token(user_a.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_token)

    response = await async_client.patch(f"/api/v1/memories/{mem_b.id}", json={"value": "Hacked"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rest_deactivate_memory_returns_404_on_idor(async_client: AsyncClient, test_db: AsyncSession, user_a: User, user_b: User):
    """10. Test REST POST /api/v1/memories/{id}/deactivate returns 404 on IDOR attempt."""
    req_b = MemoryCreateRequest(category="user_fact", key="b.deact", value="B Deact", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    session_token = SecurityManager.create_session_token(user_a.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_token)

    response = await async_client.post(f"/api/v1/memories/{mem_b.id}/deactivate")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rest_delete_memory_returns_404_on_idor(async_client: AsyncClient, test_db: AsyncSession, user_a: User, user_b: User):
    """11. Test REST DELETE /api/v1/memories/{id} returns 404 on IDOR attempt."""
    req_b = MemoryCreateRequest(category="user_fact", key="b.del", value="B Del", source="user_ui")
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    session_token = SecurityManager.create_session_token(user_a.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_token)

    response = await async_client.delete(f"/api/v1/memories/{mem_b.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_same_key_coexists_independently_across_users(test_db: AsyncSession, user_a: User, user_b: User):
    """12. Test that User A and User B can both have identical category and key with different values."""
    req_a = MemoryCreateRequest(category="user_preference", key="preferred_db", value="PostgreSQL", source="user_ui")
    req_b = MemoryCreateRequest(category="user_preference", key="preferred_db", value="MySQL", source="user_ui")

    mem_a = await MemoryService.create_or_upsert_memory(test_db, user_a.id, req_a)
    mem_b = await MemoryService.create_or_upsert_memory(test_db, user_b.id, req_b)

    assert mem_a.id != mem_b.id
    assert mem_a.value == "PostgreSQL"
    assert mem_b.value == "MySQL"
