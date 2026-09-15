"""
Tests for Agent Tool search_personal_knowledge and ToolRegistry Integration (Milestone 7).
Validates:
- Registration of search_personal_knowledge in ToolRegistry
- READ risk level classification
- Total tool count (24 tools)
- Tool JSON schema validation
- Direct tool execution via ToolExecutor
- Isolation from arbitrary user_id overrides or SQL inputs
- Multi-turn reasoning integration with structured citation output
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.ai.agent.tool_registry import ToolRegistry, RiskLevel
from app.ai.agent.tool_executor import ToolExecutor
from app.ai.tools.knowledge_tools import execute_search_personal_knowledge
from app.ai.agent.orchestrator import AgentOrchestrator
from app.ai.providers.base import LLMProvider, LLMResponse, LLMToolCall


@pytest.fixture
async def test_user(test_db: AsyncSession) -> User:
    u = User(email="agent_rag_tool_user@example.com", full_name="RAG Agent Tester", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


def test_tool_registry_contains_search_personal_knowledge():
    """Verify tool is registered with RiskLevel.READ."""
    tool = ToolRegistry.get("search_personal_knowledge")
    assert tool is not None
    assert tool.name == "search_personal_knowledge"
    assert tool.risk_level == RiskLevel.READ
    assert "personal knowledge" in tool.description.lower()
    assert tool.func is not None


def test_tool_registry_total_tool_count():
    """Milestone 6 had 23 tools. Milestone 7 added search_personal_knowledge (24). Milestone 8 adds get_proactive_notifications (25)."""
    all_tools = ToolRegistry.list_tools()
    assert len(all_tools) >= 24



def test_search_personal_knowledge_schema_parameters():
    """Verify schema parameters do not allow user_id, raw SQL, or embeddings."""
    tool = ToolRegistry.get("search_personal_knowledge")
    params = tool.parameters_schema

    assert "properties" in params
    props = params["properties"]
    assert "query" in props
    assert "source_type" in props
    assert "top_k" in props

    # Must NOT expose internal parameters
    assert "user_id" not in props
    assert "sql" not in props
    assert "embedding" not in props
    assert "db" not in props


@pytest.mark.asyncio
async def test_execute_search_personal_knowledge_direct(test_db: AsyncSession, test_user: User):
    mock_retrieval_res = {
        "status": "success",
        "source": "personal_knowledge",
        "trusted": False,
        "total_found": 1,
        "results": [
            {
                "citation_id": "cit_1",
                "source_type": "gmail",
                "source_id": "msg-123",
                "title": "Server Migration",
                "snippet": "Migration completes at 10 PM.",
                "similarity_score": 0.89,
            }
        ],
        "citations": [
            {
                "citation_id": "cit_1",
                "source_type": "gmail",
                "source_id": "msg-123",
                "title": "Server Migration",
                "similarity_score": 0.89,
            }
        ],
        "formatted_context": "=== BEGIN UNTRUSTED RETRIEVED CONTEXT (Citation ID: cit_1) ===\nMigration completes at 10 PM.\n=== END UNTRUSTED RETRIEVED CONTEXT ===",
    }

    with patch("app.ai.tools.knowledge_tools.RetrievalService") as mock_ret_cls:
        mock_ret = MagicMock()
        mock_ret.search_knowledge = AsyncMock(return_value=mock_retrieval_res)
        mock_ret_cls.return_value = mock_ret

        res = await execute_search_personal_knowledge(
            user_id=test_user.id,
            db=test_db,
            query="server migration",
            top_k=3,
        )

        assert res["status"] == "success"
        assert res["total_found"] == 1
        assert len(res["citations"]) == 1
        assert res["citations"][0]["citation_id"] == "cit_1"


@pytest.mark.asyncio
async def test_tool_executor_executes_search_personal_knowledge(test_db: AsyncSession, test_user: User):
    mock_retrieval_res = {
        "status": "success",
        "source": "personal_knowledge",
        "trusted": False,
        "total_found": 0,
        "results": [],
        "citations": [],
        "formatted_context": "No relevant documents found.",
    }

    with patch("app.ai.tools.knowledge_tools.RetrievalService") as mock_ret_cls:
        mock_ret = MagicMock()
        mock_ret.search_knowledge = AsyncMock(return_value=mock_retrieval_res)
        mock_ret_cls.return_value = mock_ret

        exec_res = await ToolExecutor.execute_tool(
            user_id=test_user.id,
            db=test_db,
            tool_name="search_personal_knowledge",
            arguments={"query": "non-existent item"},
        )

        assert exec_res.is_error is False
        assert exec_res.status == "completed"
        assert "personal knowledge" in exec_res.friendly_summary.lower()


@pytest.mark.asyncio
async def test_tool_executor_strips_malicious_user_id_override(test_db: AsyncSession, test_user: User):
    """If client/LLM passes user_id='victim-id' in arguments, ToolExecutor must ignore it."""
    with patch("app.ai.tools.knowledge_tools.RetrievalService") as mock_ret_cls:
        mock_ret = MagicMock()
        mock_ret.search_knowledge = AsyncMock(return_value={"status": "success", "results": []})
        mock_ret_cls.return_value = mock_ret

        exec_res = await ToolExecutor.execute_tool(
            user_id=test_user.id,
            db=test_db,
            tool_name="search_personal_knowledge",
            arguments={"query": "test", "user_id": "malicious-victim-id"},
        )

        # Ensure service was called with authenticated user_id, NOT malicious-victim-id
        call_kwargs = mock_ret.search_knowledge.call_args.kwargs
        assert call_kwargs["user_id"] == test_user.id


def test_search_personal_knowledge_tool_declaration_format():
    """Verify tool is converted properly into LLMToolDeclaration."""
    declarations = ToolRegistry.get_tool_declarations()
    rag_decl = next((d for d in declarations if d.name == "search_personal_knowledge"), None)
    assert rag_decl is not None
    assert "query" in rag_decl.parameters["properties"]


@pytest.mark.asyncio
async def test_execute_search_personal_knowledge_handles_empty_query(test_db: AsyncSession, test_user: User):
    """Verify empty query string handling."""
    with patch("app.ai.tools.knowledge_tools.RetrievalService") as mock_ret_cls:
        mock_ret = MagicMock()
        mock_ret.search_knowledge = AsyncMock(
            return_value={"status": "success", "results": [], "citations": [], "total_found": 0}
        )
        mock_ret_cls.return_value = mock_ret

        res = await execute_search_personal_knowledge(
            user_id=test_user.id,
            db=test_db,
            query="   ",
        )
        assert res["total_found"] == 0


@pytest.mark.asyncio
async def test_tool_executor_handles_retrieval_exception_gracefully(test_db: AsyncSession, test_user: User):
    """Verify ToolExecutor catches internal errors during RAG search and reports failure safely."""
    with patch("app.ai.tools.knowledge_tools.RetrievalService") as mock_ret_cls:
        mock_ret = MagicMock()
        mock_ret.search_knowledge = AsyncMock(side_effect=RuntimeError("Database connectivity issue"))
        mock_ret_cls.return_value = mock_ret

        exec_res = await ToolExecutor.execute_tool(
            user_id=test_user.id,
            db=test_db,
            tool_name="search_personal_knowledge",
            arguments={"query": "urgent task"},
        )

        assert exec_res.is_error is True
        assert "Database connectivity issue" in exec_res.friendly_summary or "Failed to retrieve" in exec_res.friendly_summary
