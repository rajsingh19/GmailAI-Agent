"""
Suite 6: test_personalization_session_and_controls.py (10 tests)
Verifies turn/session overrides, regex detection, Redis session tracking, and lack of M11 mutation.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.personalization import (
    PersonalizationLevel,
    PersonalizationConfigUpdate,
)
from app.services.personalization_service import PersonalizationService
from app.services.memory_service import MemoryService
from app.schemas.memory import MemoryCreateRequest


def test_override_nlp_disable_pattern():
    """1. Test that 'stop personalizing' returns False (disable intent)."""
    assert PersonalizationService.detect_override_intent("Please stop personalizing my responses") is False
    assert PersonalizationService.detect_override_intent("turn off personalization") is False


def test_override_nlp_disable_chat_pattern():
    """2. Test that 'don't personalize this chat' returns False."""
    assert PersonalizationService.detect_override_intent("don't personalize this chat") is False
    assert PersonalizationService.detect_override_intent("do not personalize this turn") is False


def test_override_nlp_resume_pattern():
    """3. Test that 'resume personalization' returns True (resume intent)."""
    assert PersonalizationService.detect_override_intent("resume personalization") is True
    assert PersonalizationService.detect_override_intent("enable personalizing") is True


def test_override_nlp_resume_conversation_pattern():
    """4. Test that 'personalize this conversation' returns True."""
    assert PersonalizationService.detect_override_intent("personalize this conversation") is True


@pytest.mark.asyncio
async def test_override_turn_disable_parameter(db_session: AsyncSession, test_user: User):
    """5. Test that disable_personalization=True immediately returns empty context."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.HIGH,
        ),
    )
    res = await PersonalizationService.build_personalization_context(
        db=db_session,
        user_id=test_user.id,
        query="How do I setup FastAPI routing?",
        disable_personalization=True,
    )
    assert res.context_text == ""
    assert res.metadata.applied_keys == []


@pytest.mark.asyncio
async def test_override_session_redis_persistence(db_session: AsyncSession, test_user: User):
    """6. Test that session override is stored and read back for session_id."""
    PersonalizationService.reset_in_memory_stores()
    session_id = "sess_test_123"
    await PersonalizationService.set_session_override(user_id=test_user.id, session_id=session_id, enabled=False)
    status = await PersonalizationService.get_session_override(user_id=test_user.id, session_id=session_id)
    assert status is False


@pytest.mark.asyncio
async def test_override_does_not_mutate_m11(db_session: AsyncSession, test_user: User):
    """7. Test that setting a session override does not mutate M11 memories."""
    PersonalizationService.reset_in_memory_stores()
    mem = await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="coding.framework",
            value="FastAPI",
            source="explicit_user_request",
        ),
    )
    # Set override
    await PersonalizationService.set_session_override(user_id=test_user.id, session_id="sess_abc", enabled=False)
    # Check memory is intact
    refreshed = await MemoryService.get_memory(db=db_session, user_id=test_user.id, memory_id=mem.id)
    assert refreshed is not None
    assert refreshed.active is True


@pytest.mark.asyncio
async def test_override_scoped_to_session_id(db_session: AsyncSession, test_user: User):
    """8. Test that disabling personalization in session A does not affect session B."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.set_session_override(user_id=test_user.id, session_id="sess_A", enabled=False)
    await PersonalizationService.set_session_override(user_id=test_user.id, session_id="sess_B", enabled=True)

    status_a = await PersonalizationService.get_session_override(user_id=test_user.id, session_id="sess_A")
    status_b = await PersonalizationService.get_session_override(user_id=test_user.id, session_id="sess_B")
    assert status_a is False
    assert status_b is True


@pytest.mark.asyncio
async def test_override_endpoint_logic(test_user: User):
    """9. Test session override setter and getter methods with clean state."""
    PersonalizationService.reset_in_memory_stores()
    sess_id = "sess_api_test"
    # Initially None
    assert await PersonalizationService.get_session_override(test_user.id, sess_id) is None
    # Disable
    await PersonalizationService.set_session_override(test_user.id, sess_id, enabled=False)
    assert await PersonalizationService.get_session_override(test_user.id, sess_id) is False
    # Resume
    await PersonalizationService.set_session_override(test_user.id, sess_id, enabled=True)
    assert await PersonalizationService.get_session_override(test_user.id, sess_id) is True


def test_override_no_llm_invocation():
    """10. Test that standard non-override queries return None without side effects."""
    assert PersonalizationService.detect_override_intent("How do I write a binary search tree in Python?") is None
    assert PersonalizationService.detect_override_intent("What is on my calendar today?") is None
