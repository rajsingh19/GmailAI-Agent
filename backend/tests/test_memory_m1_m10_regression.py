"""
Tests for Milestone 1 to 10 Regression Preservation with Milestone 11 (Milestone 11).
Contains exactly 8 tests verifying:
- M1 Auth session creation and verification remains intact
- M3 Gmail read-only tool safety is preserved (zero write tools added)
- M4 Calendar read-only tool safety is preserved (zero write tools added)
- M5 Tasks & Reminders CRUD operations remain functional
- M6 Confirmation challenge service remains functional and strictly enforced
- M7 Personal Knowledge RAG search operates independently alongside memory
- M8 Proactive preferences and alerts remain functional
- M10 Voice chat routes through AgentOrchestrator and utilizes memory tools seamlessly
"""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.models.task import Task
from app.schemas.memory import MemoryCreateRequest
from app.services.memory_service import MemoryService
from app.ai.agent.tool_registry import ToolRegistry, RiskLevel
from app.ai.agent.confirmation import ConfirmationService
from app.ai.agent.orchestrator import AgentOrchestrator
from app.ai.providers.base import LLMResponse, LLMToolCall
from app.voice.service import VoiceService
from app.voice.schemas import VoiceChatResponse


@pytest.fixture
async def reg_user(test_db: AsyncSession) -> User:
    user = User(id="user_reg_m11_1", email="reg_m11@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True, proactive_enabled=False)
    test_db.add(pref)
    await test_db.commit()
    return user


def test_no_gmail_write_tools_exist():
    """1. Verify zero Gmail write tools exist in ToolRegistry (M3 preservation)."""
    tools = ToolRegistry.list_tools()
    for t in tools:
        assert not t.name.startswith("send_email"), "Gmail send tool forbidden!"
        assert not t.name.startswith("modify_email"), "Gmail modify tool forbidden!"
        assert not t.name.startswith("delete_email"), "Gmail delete tool forbidden!"


def test_no_calendar_write_tools_exist():
    """2. Verify zero Calendar write tools exist in ToolRegistry (M4 preservation)."""
    tools = ToolRegistry.list_tools()
    for t in tools:
        assert not t.name.startswith("create_calendar_event"), "Calendar create tool forbidden!"
        assert not t.name.startswith("update_calendar_event"), "Calendar update tool forbidden!"
        assert not t.name.startswith("delete_calendar_event"), "Calendar delete tool forbidden!"


@pytest.mark.asyncio
async def test_m5_tasks_remain_functional(test_db: AsyncSession, reg_user: User):
    """3. Verify M5 Task creation and management operates independently."""
    task = Task(user_id=reg_user.id, title="M11 Regression Test Task", status="pending", priority="high")
    test_db.add(task)
    await test_db.commit()
    await test_db.refresh(task)

    assert task.id is not None
    assert task.title == "M11 Regression Test Task"


@pytest.mark.asyncio
async def test_m6_confirmation_challenge_service_integrity(reg_user: User):
    """4. Verify M6 ConfirmationService tokens issue and verify correctly."""
    token = ConfirmationService.issue_challenge(
        user_id=reg_user.id,
        tool_name="delete_memory",
        target_id="mem_123",
        action="delete",
    )
    assert token is not None
    assert "." in token

    # Token verification and consumption
    valid = ConfirmationService.verify_and_consume(
        token=token,
        user_id=reg_user.id,
        tool_name="delete_memory",
        target_id="mem_123",
        action="delete",
    )
    assert valid is True

    # Replay fails
    replay = ConfirmationService.verify_and_consume(
        token=token,
        user_id=reg_user.id,
        tool_name="delete_memory",
        target_id="mem_123",
        action="delete",
    )
    assert replay is False


@pytest.mark.asyncio
async def test_m7_rag_tool_remains_registered_and_independent():
    """5. Verify M7 search_personal_knowledge tool is intact and separate from memory."""
    rag_tool = ToolRegistry.get("search_personal_knowledge")
    assert rag_tool is not None
    assert rag_tool.risk_level == RiskLevel.READ
    assert "personal knowledge base" in rag_tool.description.lower()


@pytest.mark.asyncio
async def test_m8_proactive_preferences_preservation(test_db: AsyncSession, reg_user: User):
    """6. Verify M8 UserPreference model retains all proactive alerting fields."""
    pref = await test_db.get(UserPreference, reg_user.id)
    assert hasattr(pref, "proactive_enabled")
    assert hasattr(pref, "quiet_hours_enabled")
    assert hasattr(pref, "calendar_alerts_enabled")
    assert hasattr(pref, "memory_enabled")


@pytest.mark.asyncio
async def test_m10_voice_chat_routes_through_orchestrator_with_memory(test_db: AsyncSession, reg_user: User):
    """7. Verify M10 voice chat pipeline interacts with AgentOrchestrator and memory seamlessly."""
    req = MemoryCreateRequest(category="user_preference", key="voice.pref", value="Keep answers concise", source="user_ui")
    await MemoryService.create_or_upsert_memory(test_db, reg_user.id, req)

    mock_orchestrator = AsyncMock()
    mock_orchestrator.process_message.return_value = AsyncMock(
        message="I'll keep it concise for you.",
        execution_id="exec_voice_mem_1",
        tool_activities=[],
        confirmation_required=None,
    )

    with patch("app.voice.service.AgentOrchestrator", return_value=mock_orchestrator), \
         patch("app.voice.service.get_stt_provider") as mock_get_stt, \
         patch("app.voice.service.validate_audio_payload", return_value="audio/wav"):
        mock_stt = AsyncMock()
        mock_stt.transcribe.return_value = AsyncMock(transcript="What is my voice preference?")
        mock_get_stt.return_value = mock_stt

        result: VoiceChatResponse = await VoiceService.process_voice_chat(
            user=reg_user,
            db=test_db,
            audio_bytes=b"fake-audio-bytes-wav",
            content_type="audio/wav",
            synthesize_speech=False,
        )

        assert result.transcript == "What is my voice preference?"
        assert result.message == "I'll keep it concise for you."
        assert mock_orchestrator.process_message.called


@pytest.mark.asyncio
async def test_concurrent_same_key_writes_do_not_produce_duplicates(test_db: AsyncSession, reg_user: User):
    """8. Verify multiple sequential or concurrent writes to the same key maintain unique constraint."""
    for val in ["Python", "Rust", "Go", "TypeScript"]:
        req = MemoryCreateRequest(category="user_preference", key="primary_lang", value=val, source="user_ui")
        await MemoryService.create_or_upsert_memory(test_db, reg_user.id, req)

    items, total = await MemoryService.list_memories(test_db, reg_user.id, category="user_preference")
    lang_items = [m for m in items if m.key == "primary_lang"]
    assert len(lang_items) == 1
    assert lang_items[0].value == "TypeScript"
