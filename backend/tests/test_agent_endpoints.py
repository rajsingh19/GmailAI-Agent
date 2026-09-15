"""
Tests for AI Agent API Endpoints (Milestone 6).
Verifies:
- POST /api/v1/agent/chat authentication requirements (401)
- GET /api/v1/agent/tools authentication requirements (401)
- GET /api/v1/agent/tools returns registered tool schemas and risk levels
- POST /api/v1/agent/chat executes agent flow and returns structured response
- Multi-user isolation across chat endpoints
- Zero secret leakage in API responses
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.models.task import Task
from app.ai.providers.base import LLMResponse, LLMToolCall


async def create_test_user(test_db: AsyncSession, email: str = "agent_endpoint_user@example.com") -> User:
    user = User(email=email, full_name="Agent Endpoint Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_agent_endpoints_require_authentication(async_client: AsyncClient):
    """Verify agent endpoints reject unauthenticated requests with 401 Unauthorized."""
    # GET /api/v1/agent/tools
    tools_res = await async_client.get("/api/v1/agent/tools")
    assert tools_res.status_code == 401

    # POST /api/v1/agent/chat
    chat_res = await async_client.post(
        "/api/v1/agent/chat",
        json={"message": "Hello Assistant"}
    )
    assert chat_res.status_code == 401


@pytest.mark.asyncio
async def test_get_agent_tools_authenticated(async_client: AsyncClient, test_db: AsyncSession):
    """Verify authenticated user can retrieve tool declarations and risk levels."""
    user = await create_test_user(test_db, "tools_user@example.com")
    set_auth_cookie(async_client, user)

    response = await async_client.get("/api/v1/agent/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert "total" in data
    assert data["total"] > 0

    tool_names = [t["name"] for t in data["tools"]]
    # Verify core tools are declared
    assert "create_task" in tool_names
    assert "list_tasks" in tool_names
    assert "delete_task" in tool_names
    assert "create_reminder" in tool_names
    assert "list_reminders" in tool_names
    assert "search_gmail" in tool_names
    assert "list_calendar_events" in tool_names

    # Verify risk levels
    del_task_tool = next(t for t in data["tools"] if t["name"] == "delete_task")
    assert del_task_tool["risk_level"] == "HIGH_RISK_WRITE"

    list_task_tool = next(t for t in data["tools"] if t["name"] == "list_tasks")
    assert list_task_tool["risk_level"] == "READ"


@pytest.mark.asyncio
async def test_post_agent_chat_direct_message(async_client: AsyncClient, test_db: AsyncSession):
    """Verify authenticated user can send chat message and receive AI response."""
    user = await create_test_user(test_db, "chat_direct_user@example.com")
    set_auth_cookie(async_client, user)

    mock_llm_response = LLMResponse(content="I am ready to help organize your schedule.")

    with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response") as mock_generate:
        mock_generate.return_value = mock_llm_response

        response = await async_client.post(
            "/api/v1/agent/chat",
            json={
                "message": "Hello! What can you do?",
                "history": []
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "I am ready to help organize your schedule."
        assert data["confirmation_required"] is None
        assert isinstance(data["tool_activities"], list)


@pytest.mark.asyncio
async def test_post_agent_chat_with_tool_invocation(async_client: AsyncClient, test_db: AsyncSession):
    """Verify chat endpoint executes tools and summarizes results."""
    user = await create_test_user(test_db, "chat_tool_user@example.com")
    set_auth_cookie(async_client, user)

    # Seed a task
    task = Task(
        user_id=user.id,
        title="Quarterly Review Task",
        status="pending",
        priority="high"
    )
    test_db.add(task)
    await test_db.commit()

    # Step 1: LLM invokes list_tasks
    step1 = LLMResponse(
        content=None,
        tool_calls=[LLMToolCall(id="t1", name="list_tasks", arguments={"status": "pending"})]
    )
    # Step 2: LLM summarizes
    step2 = LLMResponse(
        content="You have 1 pending task: 'Quarterly Review Task'."
    )

    with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", side_effect=[step1, step2]):
        response = await async_client.post(
            "/api/v1/agent/chat",
            json={"message": "Show my tasks"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "Quarterly Review Task" in data["message"]
        assert len(data["tool_activities"]) == 1
        assert data["tool_activities"][0]["name"] == "Listing tasks"
        assert data["tool_activities"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_post_agent_chat_high_risk_confirmation_challenge(async_client: AsyncClient, test_db: AsyncSession):
    """Verify chat endpoint generates cryptographic challenge when LLM attempts deletion."""
    user = await create_test_user(test_db, "chat_delete_user@example.com")
    set_auth_cookie(async_client, user)

    task = Task(
        user_id=user.id,
        title="Task To Delete Via AI",
        status="pending",
        priority="low"
    )
    test_db.add(task)
    await test_db.commit()
    await test_db.refresh(task)

    # Step 1: LLM calls delete_task without confirmation token
    step1 = LLMResponse(
        content=None,
        tool_calls=[LLMToolCall(id="del-1", name="delete_task", arguments={"task_id": task.id})]
    )

    with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=step1):
        response = await async_client.post(
            "/api/v1/agent/chat",
            json={"message": f"Delete task {task.id}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["confirmation_required"] is not None
        assert data["confirmation_required"]["target_id"] == task.id
        challenge_token = data["confirmation_required"]["confirmation_token"]
        assert challenge_token is not None

    # Step 2: Now send message with valid confirmation token
    # Tool executes deletion -> LLM summarizes
    step2_del_call = LLMResponse(
        content=None,
        tool_calls=[LLMToolCall(id="del-2", name="delete_task", arguments={"task_id": task.id})]
    )
    step2_summary = LLMResponse(
        content="Task 'Task To Delete Via AI' has been deleted successfully."
    )

    with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", side_effect=[step2_del_call, step2_summary]):
        confirmed_response = await async_client.post(
            "/api/v1/agent/chat",
            json={
                "message": "Yes, I confirm deletion",
                "confirmation_token": challenge_token
            }
        )

        assert confirmed_response.status_code == 200
        confirmed_data = confirmed_response.json()
        assert confirmed_data["confirmation_required"] is None
        assert len(confirmed_data["tool_activities"]) == 1
        assert confirmed_data["tool_activities"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_zero_secret_leakage_in_agent_responses(async_client: AsyncClient, test_db: AsyncSession):
    """Verify Gemini API key and internal secrets are never returned in endpoint responses."""
    user = await create_test_user(test_db, "zero_leak_user@example.com")
    set_auth_cookie(async_client, user)

    mock_llm_response = LLMResponse(content="Response from AI model.")

    with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=mock_llm_response):
        response = await async_client.post(
            "/api/v1/agent/chat",
            json={"message": "System info"}
        )

        assert response.status_code == 200
        body_text = response.text
        assert "GEMINI_API_KEY" not in body_text
        assert "ENCRYPTION_KEY" not in body_text
        assert "SECRET_KEY" not in body_text
        assert "DATABASE_URL" not in body_text


@pytest.mark.asyncio
async def test_post_agent_chat_empty_message_validation_error(async_client: AsyncClient, test_db: AsyncSession):
    """Verify empty or missing message fails Pydantic validation (422)."""
    user = await create_test_user(test_db, "empty_msg_user@example.com")
    set_auth_cookie(async_client, user)

    # Empty string message
    res = await async_client.post(
        "/api/v1/agent/chat",
        json={"message": ""}
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_post_agent_chat_cross_user_confirmation_rejection(async_client: AsyncClient, test_db: AsyncSession):
    """Verify confirmation challenge generated for user A cannot be used by user B."""
    user_a = await create_test_user(test_db, "user_a_confirm@example.com")
    user_b = await create_test_user(test_db, "user_b_confirm@example.com")

    # Generate valid challenge token for user_a
    from app.ai.agent.confirmation import ConfirmationService
    challenge_token = ConfirmationService.issue_challenge(
        user_id=user_a.id,
        tool_name="delete_task",
        target_id="task-123",
        action="delete"
    )

    # User B tries to submit user A's token
    set_auth_cookie(async_client, user_b)
    step_call = LLMResponse(
        content=None,
        tool_calls=[LLMToolCall(id="del-1", name="delete_task", arguments={"task_id": "task-123"})]
    )

    with patch("app.ai.providers.gemini_provider.GeminiProvider.generate_response", return_value=step_call):
        response = await async_client.post(
            "/api/v1/agent/chat",
            json={
                "message": "Delete task 123",
                "confirmation_token": challenge_token
            }
        )

        assert response.status_code == 200
        data = response.json()
        # Confirmation should fail validation for user B, returning a new confirmation requirement
        assert data["confirmation_required"] is not None


@pytest.mark.asyncio
async def test_get_agent_tools_schema_structure(async_client: AsyncClient, test_db: AsyncSession):
    """Verify all tool definitions conform to required JSON schema format."""
    user = await create_test_user(test_db, "tools_schema_user@example.com")
    set_auth_cookie(async_client, user)

    response = await async_client.get("/api/v1/agent/tools")
    assert response.status_code == 200
    data = response.json()

    for tool in data["tools"]:
        assert "name" in tool
        assert "description" in tool
        assert "risk_level" in tool
        assert "parameters" in tool
        assert isinstance(tool["parameters"], dict)
        assert tool["risk_level"] in ["READ", "LOW_RISK_WRITE", "HIGH_RISK_WRITE"]


