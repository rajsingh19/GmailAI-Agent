"""
Tests for Memory CRUD & Service Layer (Milestone 11).
Contains exactly 12 unit tests verifying:
- Memory creation (explicit, user_ui, agent_inference)
- Provenance and confidence score setting
- Atomic upsert and update on conflict
- Pagination, category filtering, and active filtering
- Soft deactivation and reactivation
- Hard deletion
- Memory enabled check
- Aggregated stats computation
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.schemas.memory import MemoryCreateRequest, MemoryUpdateRequest
from app.services.memory_service import MemoryService


@pytest.fixture
async def sample_user(test_db: AsyncSession) -> User:
    """Fixture providing an active test user."""
    user = User(
        id="user_memory_crud_1",
        email="mem_crud@example.com",
        full_name="Memory CRUD User",
        is_active=True,
    )
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_create_explicit_user_memory(test_db: AsyncSession, sample_user: User):
    """1. Test creating an explicit user memory sets confidence=EXPLICIT and explicitly_confirmed=True."""
    req = MemoryCreateRequest(
        category="user_preference",
        key="coding.language",
        value="Python",
        description="User prefers Python 3.12",
        source="explicit_user_request",
    )
    mem = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req)
    assert mem.id is not None
    assert mem.user_id == sample_user.id
    assert mem.category == "user_preference"
    assert mem.key == "coding.language"
    assert mem.value == "Python"
    assert mem.confidence == "EXPLICIT"
    assert mem.confidence_score == 1.0
    assert mem.explicitly_confirmed is True
    assert mem.active is True


@pytest.mark.asyncio
async def test_create_inferred_memory_starts_inactive_and_unconfirmed(test_db: AsyncSession, sample_user: User):
    """2. Test creating an inferred memory sets explicitly_confirmed=False and active=False."""
    req = MemoryCreateRequest(
        category="workflow_preference",
        key="git.commit_style",
        value="Conventional Commits",
        source="agent_inference",
        confidence="MEDIUM_CONFIDENCE",
        explicitly_confirmed=False,
    )
    mem = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req)
    assert mem.confidence == "MEDIUM_CONFIDENCE"
    assert mem.confidence_score == 0.65
    assert mem.explicitly_confirmed is False
    assert mem.active is False


@pytest.mark.asyncio
async def test_upsert_same_key_replaces_value_and_reactivates(test_db: AsyncSession, sample_user: User):
    """3. Test upserting a new value for the same category and key replaces the value cleanly."""
    req1 = MemoryCreateRequest(
        category="user_preference",
        key="framework.backend",
        value="Flask",
        source="explicit_user_request",
    )
    mem1 = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req1)
    assert mem1.value == "Flask"

    # Deactivate
    await MemoryService.deactivate_memory(test_db, sample_user.id, mem1.id)

    # Upsert new preference
    req2 = MemoryCreateRequest(
        category="user_preference",
        key="framework.backend",
        value="FastAPI",
        description="Switched to FastAPI",
        source="explicit_user_request",
    )
    mem2 = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req2)
    assert mem2.id == mem1.id
    assert mem2.value == "FastAPI"
    assert mem2.description == "Switched to FastAPI"
    assert mem2.active is True  # Reactivated


@pytest.mark.asyncio
async def test_get_memory_by_id(test_db: AsyncSession, sample_user: User):
    """4. Test retrieving a specific memory by ID."""
    req = MemoryCreateRequest(
        category="user_fact",
        key="location.city",
        value="San Francisco",
        source="user_ui",
    )
    mem = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req)
    retrieved = await MemoryService.get_memory(test_db, sample_user.id, mem.id)
    assert retrieved is not None
    assert retrieved.key == "location.city"
    assert retrieved.value == "San Francisco"


@pytest.mark.asyncio
async def test_get_nonexistent_memory_returns_none(test_db: AsyncSession, sample_user: User):
    """5. Test get_memory returns None for a nonexistent ID."""
    retrieved = await MemoryService.get_memory(test_db, sample_user.id, "nonexistent-id")
    assert retrieved is None


@pytest.mark.asyncio
async def test_list_memories_pagination_and_total(test_db: AsyncSession, sample_user: User):
    """6. Test list_memories pagination and total counting."""
    for i in range(5):
        req = MemoryCreateRequest(
            category="project_context",
            key=f"project.module_{i}",
            value=f"Module {i} details",
            source="user_ui",
        )
        await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req)

    items, total = await MemoryService.list_memories(test_db, sample_user.id, category="project_context", limit=3, offset=0)
    assert total >= 5
    assert len(items) == 3


@pytest.mark.asyncio
async def test_list_memories_category_filter(test_db: AsyncSession, sample_user: User):
    """7. Test filtering memories by specific category."""
    req1 = MemoryCreateRequest(category="user_preference", key="pref.theme", value="dark", source="user_ui")
    req2 = MemoryCreateRequest(category="user_fact", key="fact.role", value="Staff Engineer", source="user_ui")
    await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req1)
    await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req2)

    prefs, _ = await MemoryService.list_memories(test_db, sample_user.id, category="user_preference")
    assert any(m.key == "pref.theme" for m in prefs)
    assert not any(m.key == "fact.role" for m in prefs)


@pytest.mark.asyncio
async def test_update_memory_fields(test_db: AsyncSession, sample_user: User):
    """8. Test updating memory value, description, and confirmation state."""
    req = MemoryCreateRequest(
        category="user_preference",
        key="editor.ide",
        value="Vim",
        source="user_ui",
    )
    mem = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req)

    update_in = MemoryUpdateRequest(
        value="VS Code",
        description="Switched editor",
        confidence="HIGH_CONFIDENCE",
    )
    updated = await MemoryService.update_memory(test_db, sample_user.id, mem.id, update_in)
    assert updated is not None
    assert updated.value == "VS Code"
    assert updated.description == "Switched editor"
    assert updated.confidence == "HIGH_CONFIDENCE"
    assert updated.confidence_score == 0.85


@pytest.mark.asyncio
async def test_deactivate_memory(test_db: AsyncSession, sample_user: User):
    """9. Test soft deactivating a memory."""
    req = MemoryCreateRequest(category="user_preference", key="lang.db", value="PostgreSQL", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req)
    assert mem.active is True

    deactivated = await MemoryService.deactivate_memory(test_db, sample_user.id, mem.id)
    assert deactivated is not None
    assert deactivated.active is False


@pytest.mark.asyncio
async def test_delete_memory(test_db: AsyncSession, sample_user: User):
    """10. Test permanently deleting a memory."""
    req = MemoryCreateRequest(category="user_preference", key="lang.to_delete", value="DeleteMe", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req)

    deleted = await MemoryService.delete_memory(test_db, sample_user.id, mem.id)
    assert deleted is True

    # Verify not found
    retrieved = await MemoryService.get_memory(test_db, sample_user.id, mem.id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_is_memory_enabled_defaults_to_false(test_db: AsyncSession):
    """11. Test that a new user with no preferences or memory_enabled=False defaults to False."""
    new_user = User(id="user_no_pref", email="no_pref@example.com", is_active=True)
    test_db.add(new_user)
    await test_db.commit()

    enabled = await MemoryService.is_memory_enabled_for_user(test_db, new_user.id)
    assert enabled is False


@pytest.mark.asyncio
async def test_get_memory_stats(test_db: AsyncSession, sample_user: User):
    """12. Test computing memory aggregation statistics."""
    req1 = MemoryCreateRequest(category="user_preference", key="stats.k1", value="v1", source="user_ui")
    req2 = MemoryCreateRequest(category="user_fact", key="stats.k2", value="v2", source="user_ui")
    m1 = await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req1)
    await MemoryService.create_or_upsert_memory(test_db, sample_user.id, req2)
    await MemoryService.deactivate_memory(test_db, sample_user.id, m1.id)

    stats = await MemoryService.get_memory_stats(test_db, sample_user.id)
    assert stats["total_memories"] >= 2
    assert stats["active_memories"] >= 1
    assert stats["inactive_memories"] >= 1
    assert stats["memory_enabled"] is True
    assert "user_preference" in stats["by_category"]
    assert "user_fact" in stats["by_category"]
