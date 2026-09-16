"""
Suite 3: test_personalization_conflict_resolution.py (10 tests)
Verifies conservative conflict detection, precedence of current turn, zero database mutation, and metric tracking.
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_memory import UserMemory
from app.schemas.personalization import (
    PersonalizationLevel,
    PersonalizationConfigUpdate,
)
from app.services.personalization_service import (
    PersonalizationService,
    ScoredMemory,
)
from app.services.memory_service import MemoryService
from app.schemas.memory import MemoryCreateRequest


@pytest.mark.asyncio
async def test_conflict_direct_substitution_pattern():
    """1. Test that 'use typescript instead of python' flags Python preference as conflicted."""
    mem = UserMemory(key="coding.language", value="Python", category="project_context")
    sm = ScoredMemory(memory=mem, relevance_score=30.0)
    PersonalizationService.detect_conflicts("Please use typescript instead of python for this script", [sm])
    assert sm.is_conflicted is True
    assert "typescript instead of python" in (sm.conflict_reason or "")


@pytest.mark.asyncio
async def test_conflict_explicit_negation_pattern():
    """2. Test that 'don't use react' flags React preference as conflicted."""
    mem = UserMemory(key="frontend.framework", value="React", category="project_context")
    sm = ScoredMemory(memory=mem, relevance_score=30.0)
    PersonalizationService.detect_conflicts("Please don't use react in this component", [sm])
    assert sm.is_conflicted is True
    assert "avoid react" in (sm.conflict_reason or "")


@pytest.mark.asyncio
async def test_conflict_response_style_pattern():
    """3. Test that 'give me a detailed explanation' flags concise preference as conflicted."""
    mem = UserMemory(key="style.conciseness", value="Always give concise and brief answers", category="response_style")
    sm = ScoredMemory(memory=mem, relevance_score=30.0)
    PersonalizationService.detect_conflicts("Please give me a detailed breakdown of the architecture", [sm])
    assert sm.is_conflicted is True
    assert "detailed" in (sm.conflict_reason or "")


@pytest.mark.asyncio
async def test_conflict_current_turn_takes_precedence(db_session: AsyncSession, test_user: User):
    """4. Test that current turn explicit instruction excludes conflicted memory from applied context."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.MEDIUM,
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.framework",
            value="React",
            source="explicit_user_request",
        ),
    )
    res = await PersonalizationService.build_personalization_context(
        db=db_session,
        user_id=test_user.id,
        query="Show this component in Vue instead of React",
    )
    assert "coding.framework" not in res.metadata.applied_keys


@pytest.mark.asyncio
async def test_conflict_no_database_mutation(db_session: AsyncSession, test_user: User):
    """5. Test that detecting a conflict does NOT delete, update, or deactivate the memory in PostgreSQL."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.MEDIUM,
        ),
    )
    created = await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.orm",
            value="SQLAlchemy",
            source="explicit_user_request",
        ),
    )
    # Run conflicting query
    await PersonalizationService.build_personalization_context(
        db=db_session,
        user_id=test_user.id,
        query="Write queries with Tortoise-ORM instead of SQLAlchemy",
    )
    # Verify memory is still active and unchanged in DB
    refreshed = await MemoryService.get_memory(db=db_session, user_id=test_user.id, memory_id=created.id)
    assert refreshed is not None
    assert refreshed.active is True
    assert refreshed.value == "SQLAlchemy"


@pytest.mark.asyncio
async def test_conflict_unmatched_query_preserves_memory():
    """6. Test that a casual mention without conflict syntax does not flag conflict."""
    mem = UserMemory(key="coding.framework", value="FastAPI", category="project_context")
    sm = ScoredMemory(memory=mem, relevance_score=30.0)
    PersonalizationService.detect_conflicts("How does FastAPI compare to other frameworks?", [sm])
    assert sm.is_conflicted is False


@pytest.mark.asyncio
async def test_conflict_multi_word_technologies():
    """7. Test substitution pattern with dotted or dashed technologies like 'docker-compose'."""
    mem = UserMemory(key="devops.tool", value="docker-compose", category="project_context")
    sm = ScoredMemory(memory=mem, relevance_score=30.0)
    PersonalizationService.detect_conflicts("Switch to kubernetes instead of docker-compose", [sm])
    assert sm.is_conflicted is True


@pytest.mark.asyncio
async def test_conflict_metrics_incremented():
    """8. Test that conflict detection triggers the personalization_override_total counter."""
    from app.core.metrics import metrics_registry
    mem = UserMemory(key="coding.language", value="Python", category="project_context")
    sm = ScoredMemory(memory=mem, relevance_score=30.0)
    before = metrics_registry.get_sample_value("personalization_override_total", labels={"conflict_type": "direct_substitution"}) or 0.0
    PersonalizationService.detect_conflicts("Use Rust instead of Python", [sm])
    after = metrics_registry.get_sample_value("personalization_override_total", labels={"conflict_type": "direct_substitution"}) or 0.0
    assert after >= before + 1.0


@pytest.mark.asyncio
async def test_conflict_partial_matches_conservative():
    """9. Test that conservative conflict detection does NOT false-positive on partial substrings."""
    mem = UserMemory(key="coding.lib", value="react-router", category="project_context")
    sm = ScoredMemory(memory=mem, relevance_score=30.0)
    # Query mentions "don't stop"
    PersonalizationService.detect_conflicts("Don't stop the test suite", [sm])
    assert sm.is_conflicted is False


@pytest.mark.asyncio
async def test_conflict_does_not_mask_unrelated_preferences(db_session: AsyncSession, test_user: User):
    """10. Test that a conflict on framework does NOT mask an unaffected database preference."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.MEDIUM,
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.framework",
            value="FastAPI",
            source="explicit_user_request",
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.database",
            value="PostgreSQL",
            source="explicit_user_request",
        ),
    )
    # Query conflicts with FastAPI (use Express instead of FastAPI) but asks about Postgres
    res = await PersonalizationService.build_personalization_context(
        db=db_session,
        user_id=test_user.id,
        query="Use Express instead of FastAPI with PostgreSQL database",
    )
    assert "coding.framework" not in res.metadata.applied_keys
    assert "coding.database" in res.metadata.applied_keys
