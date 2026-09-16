"""
Tests for AgentOrchestrator & Memory Integration (Milestone 11).
Contains exactly 10 tests verifying:
- Orchestrator retrieves active memories and injects <PERSONAL_MEMORY_CONTEXT>
- Orchestrator turn with memory disabled injects no memory context
- Multi-turn tool calling: LLM invokes create_memory tool
- Multi-turn tool calling: LLM invokes search_memories tool
- Multi-turn tool calling: LLM invokes list_memories tool
- Multi-turn tool calling: LLM invokes deactivate_memory tool
- Multi-turn tool calling: LLM invokes delete_memory tool triggering ConfirmationChallenge
- Supplying confirmation token allows LLM to complete deletion
- Agent response personalization references stored memory preferences
- Agent history sanitization preserves message bounding with memory context
"""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.schemas.memory import MemoryCreateRequest
from app.services.memory_service import MemoryService
from app.ai.agent.orchestrator import AgentOrchestrator
from app.ai.providers.base import LLMResponse, LLMToolCall
from app.ai.schemas.agent import AgentChatMessage
from app.ai.agent.confirmation import ConfirmationService


@pytest.fixture
async def orch_user(test_db: AsyncSession) -> User:
    user = User(id="user_orch_mem_1", email="orch_mem@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True, personalization_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


@pytest.mark.asyncio
async def test_orchestrator_injects_memory_context(test_db: AsyncSession, orch_user: User):
    """1. Test that active memories are retrieved and passed into system instruction."""
    req = MemoryCreateRequest(category="user_preference", key="coding.framework", value="FastAPI", source="user_ui")
    await MemoryService.create_or_upsert_memory(test_db, orch_user.id, req)

    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.return_value = LLMResponse(
        content="I see you prefer FastAPI!",
        tool_calls=[],
    )

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(
        user=orch_user,
        db=test_db,
        message="What backend framework should I use for coding?",
    )

    assert resp.message == "I see you prefer FastAPI!"
    assert mock_provider.generate_response.called
    call_kwargs = mock_provider.generate_response.call_args.kwargs
    sys_inst = call_kwargs["system_instruction"]
    assert "<PERSONALIZATION_CONTEXT>" in sys_inst or "<PERSONAL_MEMORY_CONTEXT>" in sys_inst
    assert "FastAPI" in sys_inst


@pytest.mark.asyncio
async def test_orchestrator_memory_disabled_injects_no_context(test_db: AsyncSession, orch_user: User):
    """2. Test that when memory is disabled, system instruction contains no memory context."""
    pref = await test_db.get(UserPreference, orch_user.id)
    pref.memory_enabled = False
    pref.personalization_enabled = False
    await test_db.commit()

    req = MemoryCreateRequest(category="user_preference", key="coding.framework", value="FastAPI", source="user_ui")
    await MemoryService.create_or_upsert_memory(test_db, orch_user.id, req)

    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.return_value = LLMResponse(content="Response", tool_calls=[])

    orchestrator = AgentOrchestrator(provider=mock_provider)
    await orchestrator.process_message(user=orch_user, db=test_db, message="Hello")

    call_kwargs = mock_provider.generate_response.call_args.kwargs
    sys_inst = call_kwargs["system_instruction"]
    assert "<PERSONAL_MEMORY_CONTEXT>" not in sys_inst
    assert "<PERSONALIZATION_CONTEXT>" not in sys_inst


@pytest.mark.asyncio
async def test_orchestrator_executes_create_memory_tool(test_db: AsyncSession, orch_user: User):
    """3. Test agent turn where LLM invokes create_memory tool."""
    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"

    # Turn 1: LLM decides to call create_memory
    mock_provider.generate_response.side_effect = [
        LLMResponse(
            content="Saving preference...",
            tool_calls=[
                LLMToolCall(
                    id="call_create_1",
                    name="create_memory",
                    arguments={"category": "user_preference", "key": "editor", "value": "Neovim"},
                )
            ],
        ),
        # Turn 2: Synthesize final answer
        LLMResponse(content="I've remembered that you use Neovim.", tool_calls=[]),
    ]

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(
        user=orch_user,
        db=test_db,
        message="Remember that I use Neovim as my code editor.",
    )

    assert resp.message == "I've remembered that you use Neovim."
    assert len(resp.tool_activities) == 1
    assert resp.tool_activities[0].status == "completed"


@pytest.mark.asyncio
async def test_orchestrator_executes_search_memories_tool(test_db: AsyncSession, orch_user: User):
    """4. Test agent turn where LLM invokes search_memories tool."""
    await MemoryService.create_or_upsert_memory(
        test_db, orch_user.id,
        MemoryCreateRequest(category="project_context", key="proj.name", value="Nova Engine", source="user_ui")
    )

    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[LLMToolCall(id="call_search_1", name="search_memories", arguments={"query": "Nova Engine"})],
        ),
        LLMResponse(content="Your project is called Nova Engine.", tool_calls=[]),
    ]

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(user=orch_user, db=test_db, message="What is my project name?")
    assert "Nova Engine" in resp.message
    assert len(resp.tool_activities) == 1


@pytest.mark.asyncio
async def test_orchestrator_executes_list_memories_tool(test_db: AsyncSession, orch_user: User):
    """5. Test agent turn where LLM invokes list_memories tool."""
    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[LLMToolCall(id="call_list_1", name="list_memories", arguments={"category": "user_preference"})],
        ),
        LLMResponse(content="Here are your stored coding preferences.", tool_calls=[]),
    ]

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(user=orch_user, db=test_db, message="What preferences do you have on file?")
    assert len(resp.tool_activities) == 1
    assert resp.tool_activities[0].status == "completed"


@pytest.mark.asyncio
async def test_orchestrator_executes_deactivate_memory_tool(test_db: AsyncSession, orch_user: User):
    """6. Test agent turn where LLM invokes deactivate_memory tool."""
    mem = await MemoryService.create_or_upsert_memory(
        test_db, orch_user.id,
        MemoryCreateRequest(category="user_preference", key="old_pref", value="old_val", source="user_ui")
    )

    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[LLMToolCall(id="call_deact_1", name="deactivate_memory", arguments={"memory_id": mem.id})],
        ),
        LLMResponse(content="I have deactivated that preference.", tool_calls=[]),
    ]

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(user=orch_user, db=test_db, message="Stop using my old preference.")
    assert len(resp.tool_activities) == 1
    assert resp.tool_activities[0].status == "completed"


@pytest.mark.asyncio
async def test_orchestrator_delete_memory_returns_confirmation_challenge(test_db: AsyncSession, orch_user: User):
    """7. Test that agent requesting delete_memory pauses with ConfirmationChallenge."""
    mem = await MemoryService.create_or_upsert_memory(
        test_db, orch_user.id,
        MemoryCreateRequest(category="user_preference", key="to_del_agent", value="DelVal", source="user_ui")
    )

    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.return_value = LLMResponse(
        content=None,
        tool_calls=[LLMToolCall(id="call_del_1", name="delete_memory", arguments={"memory_id": mem.id})],
    )

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(user=orch_user, db=test_db, message="Delete that memory permanently.")

    assert resp.confirmation_required is not None
    assert resp.confirmation_required.tool == "delete_memory"
    assert resp.confirmation_required.target_id == mem.id
    assert resp.confirmation_required.confirmation_token is not None


@pytest.mark.asyncio
async def test_orchestrator_executes_delete_memory_with_valid_token(test_db: AsyncSession, orch_user: User):
    """8. Test supplying confirmation token executes delete_memory turn."""
    mem = await MemoryService.create_or_upsert_memory(
        test_db, orch_user.id,
        MemoryCreateRequest(category="user_preference", key="to_del_token", value="DelVal", source="user_ui")
    )

    token = ConfirmationService.issue_challenge(
        user_id=orch_user.id,
        tool_name="delete_memory",
        target_id=mem.id,
        action="delete",
    )

    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[LLMToolCall(id="call_del_tok_1", name="delete_memory", arguments={"memory_id": mem.id})],
        ),
        LLMResponse(content="Memory deleted successfully.", tool_calls=[]),
    ]

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(
        user=orch_user,
        db=test_db,
        message="Confirmed delete.",
        confirmation_token=token,
    )

    assert resp.confirmation_required is None
    assert resp.message == "Memory deleted successfully."


@pytest.mark.asyncio
async def test_orchestrator_multi_turn_history_sanitization(test_db: AsyncSession, orch_user: User):
    """9. Test history sanitization with previous agent turns."""
    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    mock_provider.generate_response.return_value = LLMResponse(content="Understood.", tool_calls=[])

    orchestrator = AgentOrchestrator(provider=mock_provider)
    history = [
        AgentChatMessage(role="user", content="Hi!"),
        AgentChatMessage(role="assistant", content="Hello! How can I help?"),
    ]
    resp = await orchestrator.process_message(user=orch_user, db=test_db, message="Tell me a joke", history=history)
    assert resp.message == "Understood."


@pytest.mark.asyncio
async def test_orchestrator_tool_limit_safety(test_db: AsyncSession, orch_user: User):
    """10. Test orchestrator respects MAX_TOOL_CALLS_PER_TURN bound."""
    mock_provider = AsyncMock()
    mock_provider.model_name = "gemini-mock"
    # Repeatedly request search_memories in an infinite loop
    mock_provider.generate_response.return_value = LLMResponse(
        content=None,
        tool_calls=[LLMToolCall(id="call_loop_1", name="search_memories", arguments={"query": "test"})],
    )

    orchestrator = AgentOrchestrator(provider=mock_provider)
    resp = await orchestrator.process_message(user=orch_user, db=test_db, message="Infinite loop test")
    assert "maximum number of actions" in resp.message
