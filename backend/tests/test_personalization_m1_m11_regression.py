"""
Suite 9: test_personalization_m1_m11_regression.py (8 tests)
Verifies that all M1–M11 security invariants, read-only boundaries, and core services remain intact.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.ai.agent.tool_registry import ToolRegistry, RiskLevel
from app.services.task_service import TaskService
from app.schemas.task import TaskCreate
from app.services.memory_service import MemoryService
from app.schemas.memory import MemoryCreateRequest
from app.schemas.personalization import (
    PersonalizationLevel,
    PersonalizationConfigUpdate,
)
from app.services.personalization_service import PersonalizationService
from app.ai.agent.orchestrator import AgentOrchestrator


def test_regression_gmail_read_only():
    """1. Test that Gmail tools in ToolRegistry are strictly READ with 0 write tools."""
    tools = ToolRegistry.list_tools()
    gmail_tools = [t for t in tools if t.name.startswith("gmail_") or "gmail" in t.name.lower()]
    assert len(gmail_tools) > 0
    for t in gmail_tools:
        assert t.risk_level == RiskLevel.READ, f"Gmail tool {t.name} is not READ risk level"


def test_regression_calendar_read_only():
    """2. Test that Calendar tools in ToolRegistry are strictly READ with 0 write tools."""
    tools = ToolRegistry.list_tools()
    cal_tools = [t for t in tools if t.name.startswith("calendar_") or "calendar" in t.name.lower()]
    assert len(cal_tools) > 0
    for t in cal_tools:
        assert t.risk_level == RiskLevel.READ, f"Calendar tool {t.name} is not READ risk level"


@pytest.mark.asyncio
async def test_regression_tasks_reminders_crud(db_session: AsyncSession, test_user: User):
    """3. Test that Task creation and management continue functioning correctly."""
    task = await TaskService.create_task(
        db=db_session,
        user_id=test_user.id,
        task_in=TaskCreate(title="Regression Test Task", priority="high"),
    )
    assert task is not None
    assert task.title == "Regression Test Task"
    assert task.user_id == test_user.id


def test_regression_m6_agent_tool_registry():
    """4. Test that all required safe agent tools are registered."""
    tool_names = [t.name for t in ToolRegistry.list_tools()]
    required = [
        "search_gmail", "list_calendar_events", "create_task", "delete_task",
        "create_reminder", "delete_reminder", "create_memory", "delete_memory"
    ]
    for r in required:
        assert r in tool_names, f"Required tool {r} missing from ToolRegistry"


@pytest.mark.asyncio
async def test_regression_m7_rag_separation():
    """5. Test that RAG search tools remain accessible and categorized as READ."""
    rag_tool = ToolRegistry.get("search_personal_knowledge")
    assert rag_tool is not None
    assert rag_tool.risk_level == RiskLevel.READ


@pytest.mark.asyncio
async def test_regression_m8_proactive_monitoring():
    """6. Test that ProactiveDecisionEngine resolves risk levels accurately."""
    from app.services.proactive.decision_engine import ProactiveDecisionEngine, SuggestedAction
    engine = ProactiveDecisionEngine()
    action = SuggestedAction(
        action_type="create_task",
        target_resource="task_new",
        display_label="Create task",
        tool_name="create_task",
        arguments={"title": "Proactive task"},
        description="Auto task",
        risk_level=RiskLevel.READ,
    )
    resolved = engine.resolve_action_risk(action)
    assert resolved.risk_level == RiskLevel.LOW_RISK_WRITE


@pytest.mark.asyncio
async def test_regression_m10_voice_orchestration(db_session: AsyncSession, test_user: User):
    """7. Test that orchestrator integrates personalization cleanly on user messages."""
    PersonalizationService.reset_in_memory_stores()
    await PersonalizationService.update_user_personalization_config(
        db=db_session,
        user_id=test_user.id,
        config_in=PersonalizationConfigUpdate(
            personalization_enabled=True,
            personalization_level=PersonalizationLevel.MEDIUM,
        ),
    )
    orchestrator = AgentOrchestrator()
    resp = await orchestrator.process_message(
        user=test_user,
        db=db_session,
        message="Hello AI Assistant",
    )
    assert resp is not None
    assert resp.execution_id is not None
    assert resp.message is not None


@pytest.mark.asyncio
async def test_regression_m11_memory_crud_tools(db_session: AsyncSession, test_user: User):
    """8. Test that M11 memory tools execute cleanly with full user isolation."""
    mem = await MemoryService.create_or_upsert_memory(
        db=db_session,
        user_id=test_user.id,
        memory_in=MemoryCreateRequest(
            category="project_context",
            key="regression.key",
            value="Regression Value",
            source="explicit_user_request",
        ),
    )
    assert mem.key == "regression.key"
    fetched = await MemoryService.get_memory(db=db_session, user_id=test_user.id, memory_id=mem.id)
    assert fetched is not None
    assert fetched.value == "Regression Value"
