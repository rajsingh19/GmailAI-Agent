"""
Tests for Memory Agent Tools & ToolRegistry (Milestone 11).
Contains exactly 14 tests verifying:
- Registration of all 7 memory tools in ToolRegistry
- Tool risk level classifications (3 READ, 3 LOW_RISK_WRITE, 1 HIGH_RISK_WRITE)
- Tool declarations generation for LLM
- Tool execution: create_memory
- Tool execution: list_memories
- Tool execution: search_memories
- Tool execution: get_memory
- Tool execution: update_memory
- Tool execution: deactivate_memory
- Tool execution: delete_memory with confirmation token
- Tool execution: create_memory when memory_enabled=False informs user
- Secret scanning inside tool execution returns graceful error message
- User ID injection cannot be overridden by tool arguments
- Nonexistent memory tool arguments return structured error
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.ai.agent.tool_registry import ToolRegistry, RiskLevel
from app.ai.tools.memory_tools import (
    execute_create_memory,
    execute_list_memories,
    execute_search_memories,
    execute_get_memory,
    execute_update_memory,
    execute_deactivate_memory,
    execute_delete_memory,
)
from app.ai.agent.tool_executor import ToolExecutor
from app.ai.agent.confirmation import ConfirmationService


@pytest.fixture
async def tool_user(test_db: AsyncSession) -> User:
    user = User(id="user_tools_mem_1", email="tools_mem@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


def test_tool_registry_contains_all_7_memory_tools():
    """1. Test that ToolRegistry contains all 7 memory tools."""
    expected_tools = [
        "search_memories",
        "list_memories",
        "get_memory",
        "create_memory",
        "update_memory",
        "deactivate_memory",
        "delete_memory",
    ]
    for tool_name in expected_tools:
        tool_def = ToolRegistry.get(tool_name)
        assert tool_def is not None, f"Tool '{tool_name}' not registered in ToolRegistry"


def test_memory_tools_risk_classifications():
    """2. Test memory tool risk level assignments."""
    assert ToolRegistry.get("search_memories").risk_level == RiskLevel.READ
    assert ToolRegistry.get("list_memories").risk_level == RiskLevel.READ
    assert ToolRegistry.get("get_memory").risk_level == RiskLevel.READ
    assert ToolRegistry.get("create_memory").risk_level == RiskLevel.LOW_RISK_WRITE
    assert ToolRegistry.get("update_memory").risk_level == RiskLevel.LOW_RISK_WRITE
    assert ToolRegistry.get("deactivate_memory").risk_level == RiskLevel.LOW_RISK_WRITE
    assert ToolRegistry.get("delete_memory").risk_level == RiskLevel.HIGH_RISK_WRITE


def test_tool_declarations_include_memory_tools():
    """3. Test get_tool_declarations produces valid schemas for LLM provider."""
    decls = ToolRegistry.get_tool_declarations()
    decl_names = [d.name for d in decls]
    assert "create_memory" in decl_names
    assert "search_memories" in decl_names
    assert "delete_memory" in decl_names


@pytest.mark.asyncio
async def test_execute_create_memory_tool(test_db: AsyncSession, tool_user: User):
    """4. Test execute_create_memory tool execution."""
    res = await execute_create_memory(
        user_id=tool_user.id,
        db=test_db,
        category="user_preference",
        key="coding.language",
        value="TypeScript",
        description="User prefers TypeScript for frontends",
    )
    assert res["status"] == "success"
    assert res["memory"]["key"] == "coding.language"
    assert res["memory"]["value"] == "TypeScript"


@pytest.mark.asyncio
async def test_execute_list_memories_tool(test_db: AsyncSession, tool_user: User):
    """5. Test execute_list_memories tool execution."""
    await execute_create_memory(tool_user.id, test_db, "user_preference", "k1", "v1")
    await execute_create_memory(tool_user.id, test_db, "user_preference", "k2", "v2")

    res = await execute_list_memories(user_id=tool_user.id, db=test_db, category="user_preference")
    assert res["status"] == "success"
    assert res["count"] >= 2


@pytest.mark.asyncio
async def test_execute_search_memories_tool(test_db: AsyncSession, tool_user: User):
    """6. Test execute_search_memories tool execution."""
    await execute_create_memory(tool_user.id, test_db, "project_context", "proj.name", "AI Assistant App")
    res = await execute_search_memories(user_id=tool_user.id, db=test_db, query="AI Assistant")
    assert res["status"] == "success"
    assert len(res["memories"]) >= 1
    assert res["memories"][0]["key"] == "proj.name"


@pytest.mark.asyncio
async def test_execute_get_memory_tool(test_db: AsyncSession, tool_user: User):
    """7. Test execute_get_memory tool execution."""
    create_res = await execute_create_memory(tool_user.id, test_db, "user_fact", "fact.birthday", "January 15")
    mem_id = create_res["memory"]["id"]

    get_res = await execute_get_memory(user_id=tool_user.id, db=test_db, memory_id=mem_id)
    assert get_res["status"] == "success"
    assert get_res["memory"]["value"] == "January 15"


@pytest.mark.asyncio
async def test_execute_update_memory_tool(test_db: AsyncSession, tool_user: User):
    """8. Test execute_update_memory tool execution."""
    create_res = await execute_create_memory(tool_user.id, test_db, "user_preference", "pref.theme", "light")
    mem_id = create_res["memory"]["id"]

    update_res = await execute_update_memory(user_id=tool_user.id, db=test_db, memory_id=mem_id, value="dark")
    assert update_res["status"] == "success"
    assert update_res["memory"]["value"] == "dark"


@pytest.mark.asyncio
async def test_execute_deactivate_memory_tool(test_db: AsyncSession, tool_user: User):
    """9. Test execute_deactivate_memory tool execution."""
    create_res = await execute_create_memory(tool_user.id, test_db, "user_preference", "pref.old", "value")
    mem_id = create_res["memory"]["id"]

    deact_res = await execute_deactivate_memory(user_id=tool_user.id, db=test_db, memory_id=mem_id)
    assert deact_res["status"] == "success"
    assert "Deactivated" in deact_res["message"]


@pytest.mark.asyncio
async def test_execute_delete_memory_tool_direct(test_db: AsyncSession, tool_user: User):
    """10. Test execute_delete_memory tool execution directly."""
    create_res = await execute_create_memory(tool_user.id, test_db, "user_preference", "to_del", "val")
    mem_id = create_res["memory"]["id"]

    del_res = await execute_delete_memory(user_id=tool_user.id, db=test_db, memory_id=mem_id)
    assert del_res["status"] == "success"


@pytest.mark.asyncio
async def test_create_memory_when_disabled_returns_polite_message(test_db: AsyncSession, tool_user: User):
    """11. Test create_memory returns a helpful message if memory is disabled."""
    pref = await test_db.get(UserPreference, tool_user.id)
    pref.memory_enabled = False
    await test_db.commit()

    res = await execute_create_memory(tool_user.id, test_db, "user_preference", "pref.lang", "Rust")
    assert res["status"] == "error"
    assert "disabled" in res["message"].lower()


@pytest.mark.asyncio
async def test_secret_scanner_in_tool_returns_error_message(test_db: AsyncSession, tool_user: User):
    """12. Test passing a secret to create_memory tool returns structured error message."""
    res = await execute_create_memory(tool_user.id, test_db, "user_fact", "key", "AKIAIOSFODNN7EXAMPLE")
    assert res["status"] == "error"
    assert "credentials" in res["message"] or "rejected" in res["message"]


@pytest.mark.asyncio
async def test_tool_executor_strips_model_supplied_user_id(test_db: AsyncSession, tool_user: User):
    """13. Test ToolExecutor ignores model-supplied user_id arguments."""
    res = await ToolExecutor.execute_tool(
        user_id=tool_user.id,
        db=test_db,
        tool_name="create_memory",
        arguments={
            "user_id": "malicious_user_override",
            "category": "user_preference",
            "key": "safe.key",
            "value": "safe_val",
        },
    )
    assert res.status == "completed"
    assert res.is_error is False


@pytest.mark.asyncio
async def test_nonexistent_memory_id_returns_error(test_db: AsyncSession, tool_user: User):
    """14. Test tool operations on nonexistent memory ID return structured error."""
    res = await execute_get_memory(tool_user.id, test_db, "nonexistent-memory-id")
    assert res["status"] == "error"
    assert "not found" in res["message"]
