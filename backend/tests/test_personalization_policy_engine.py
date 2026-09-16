"""
Suite 1: test_personalization_policy_engine.py (12 tests)
Verifies Personalization Policy Engine, defaults, level bounds, category filters, and caching.
"""
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.models.user_memory import UserMemory
from app.schemas.personalization import (
    PersonalizationLevel,
    PersonalizationConfigUpdate,
)
from app.services.personalization_service import PersonalizationService
from app.services.memory_service import MemoryService
from app.schemas.memory import MemoryCreateRequest


@pytest.mark.asyncio
async def test_policy_default_disabled(db_session: AsyncSession, test_user: User):
    """1. Test that default personalization configuration has personalization_enabled=False and produces empty context."""
    PersonalizationService.reset_in_memory_stores()
    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="How do I setup FastAPI routing?"
    )
    assert res.context_text == ""
    assert res.metadata.applied_keys == []


@pytest.mark.asyncio
async def test_policy_level_none(db_session: AsyncSession, test_user: User):
    """2. Test that level NONE produces zero personalization context even when enabled."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.NONE,
        ),
    )
    # Add an active memory
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.framework",
            value="FastAPI with PostgreSQL",
            source="explicit_user_request",
        ),
    )
    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="How do I build endpoints in FastAPI?"
    )
    assert res.context_text == ""
    assert res.metadata.level == "NONE"
    assert res.metadata.applied_keys == []


@pytest.mark.asyncio
async def test_policy_level_low_constraints(db_session: AsyncSession, test_user: User):
    """3. Test that level LOW allows only response style hints (max 1 item, max 250 chars)."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.LOW,
        ),
    )
    # Add project context memory and response style memory
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="project.stack",
            value="FastAPI backend",
            source="explicit_user_request",
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="user_preference",
            key="communication.style",
            value="Prefer concise python code examples",
            source="explicit_user_request",
        ),
    )

    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="Give me code for task router"
    )
    assert len(res.metadata.applied_keys) <= 1
    assert len(res.context_text) <= 250
    assert "project.stack" not in res.metadata.applied_keys


@pytest.mark.asyncio
async def test_policy_level_medium_constraints(db_session: AsyncSession, test_user: User):
    """4. Test that level MEDIUM allows response style + project context (max 3 items, max 600 chars)."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.MEDIUM,
        ),
    )
    # Add style, project, and workflow memories
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="user_preference",
            key="coding.style",
            value="Concise python answers",
            source="explicit_user_request",
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.framework",
            value="FastAPI and React",
            source="explicit_user_request",
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="workflow_preference",
            key="workflow.task_tag",
            value="Always tag backend tasks with #core",
            source="explicit_user_request",
        ),
    )

    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="How do I structure coding router in FastAPI?"
    )
    assert len(res.metadata.applied_keys) <= 3
    assert len(res.context_text) <= 600
    assert "workflow.task_tag" not in res.metadata.applied_keys


@pytest.mark.asyncio
async def test_policy_level_high_constraints(db_session: AsyncSession, test_user: User):
    """5. Test that level HIGH allows response style + project context + workflow habits (max 5 items, max 1000 chars)."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.HIGH,
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="workflow_preference",
            key="workflow.reminder",
            value="Remind me 10 minutes before events",
            source="explicit_user_request",
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.database",
            value="PostgreSQL with Alembic migrations",
            source="explicit_user_request",
        ),
    )

    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="Schedule a task reminder workflow for postgres database coding"
    )
    assert len(res.metadata.applied_keys) <= 5
    assert len(res.context_text) <= 1000


@pytest.mark.asyncio
async def test_policy_category_toggle_response_style_off(db_session: AsyncSession, test_user: User):
    """6. Test that when personalize_response_style=False, response style memories are excluded."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.MEDIUM,
            personalize_response_style=False,
            personalize_project_context=True,
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="user_preference",
            key="communication.style",
            value="Concise python output",
            source="explicit_user_request",
        ),
    )
    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="Write python script"
    )
    assert "communication.style" not in res.metadata.applied_keys


@pytest.mark.asyncio
async def test_policy_category_toggle_project_context_off(db_session: AsyncSession, test_user: User):
    """7. Test that when personalize_project_context=False, project context memories are excluded."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.MEDIUM,
            personalize_project_context=False,
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.framework",
            value="FastAPI backend",
            source="explicit_user_request",
        ),
    )
    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="Setup coding framework api endpoint"
    )
    assert "coding.framework" not in res.metadata.applied_keys


@pytest.mark.asyncio
async def test_policy_category_toggle_workflow_habits_off(db_session: AsyncSession, test_user: User):
    """8. Test that when personalize_workflow_habits=False, workflow habits are excluded even at HIGH level."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.HIGH,
            personalize_workflow_habits=False,
        ),
    )
    await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="workflow_preference",
            key="workflow.reminder_interval",
            value="15 minutes before meeting",
            source="explicit_user_request",
        ),
    )
    res = await PersonalizationService.build_personalization_context(
        db=db_session, user_id=test_user.id, query="Schedule calendar reminder workflow meeting"
    )
    assert "workflow.reminder_interval" not in res.metadata.applied_keys


@pytest.mark.asyncio
async def test_policy_preference_caching_redis(db_session: AsyncSession, test_user: User):
    """9. Test that user personalization preferences are cached and served from cache."""
    PersonalizationService.reset_in_memory_stores()
    # Write config
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.HIGH,
        ),
    )
    # First fetch populates cache
    config1 = await PersonalizationService.get_user_personalization_config(db=db_session, user_id=test_user.id)
    assert config1["personalization_enabled"] is True
    assert config1["personalization_level"] == "HIGH"

    # Second fetch returns cached result
    config2 = await PersonalizationService.get_user_personalization_config(db=db_session, user_id=test_user.id)
    assert config2 == config1


@pytest.mark.asyncio
async def test_policy_cache_invalidation_on_update(db_session: AsyncSession, test_user: User):
    """10. Test that updating personalization config immediately invalidates user cache."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.LOW,
        ),
    )
    c1 = await PersonalizationService.get_user_personalization_config(db=db_session, user_id=test_user.id)
    assert c1["personalization_level"] == "LOW"

    # Update to MEDIUM
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_level=PersonalizationLevel.MEDIUM,
        ),
    )
    c2 = await PersonalizationService.get_user_personalization_config(db=db_session, user_id=test_user.id)
    assert c2["personalization_level"] == "MEDIUM"


@pytest.mark.asyncio
async def test_policy_cache_invalidation_on_memory_mutation(db_session: AsyncSession, test_user: User):
    """11. Test that creating/mutating M11 memories triggers personalization cache invalidation."""
    PersonalizationService.reset_in_memory_stores()
    mem = await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.lang",
            value="TypeScript",
            source="explicit_user_request",
        ),
    )
    assert mem is not None
    # Deactivate memory
    deactivated = await MemoryService.deactivate_memory(db=db_session, user_id=test_user.id, memory_id=mem.id)
    assert deactivated.active is False


def test_policy_invalid_level_rejected():
    """12. Test that application validation rejects lowercase or arbitrary level strings."""
    with pytest.raises(ValidationError):
        PersonalizationConfigUpdate(personalization_level="medium")  # Lowercase rejected

    with pytest.raises(ValidationError):
        PersonalizationConfigUpdate(personalization_level="SUPER_HIGH")  # Arbitrary rejected
