"""
Tests for AI Agent Confirmation Challenge & Cryptographic Guardrails (Milestone 6).
Verifies:
- HMAC-SHA256 signature generation and validation
- Single-use challenge token consumption
- Tampering detection and rejection
- Expired challenge rejection
- Cross-user challenge isolation
- Cross-tool and cross-target challenge isolation
- ToolExecutor confirmation interception for HIGH_RISK_WRITE tools
- Rejection of forged boolean flags (e.g. confirmed: true)
"""

import pytest
from unittest.mock import patch
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.task import Task
from app.models.reminder import Reminder
from app.ai.agent.confirmation import ConfirmationService
from app.ai.agent.tool_executor import ToolExecutor
from app.ai.agent.tool_registry import ToolRegistry, RiskLevel
from app.ai.schemas.agent import ConfirmationChallenge


async def create_test_user(test_db: AsyncSession, email: str = "confirm_test_user@example.com") -> User:
    user = User(email=email, full_name="Confirm Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def test_confirmation_service_token_lifecycle():
    """Verify standard creation and consumption of HMAC challenge tokens."""
    ConfirmationService.reset_consumed_tokens_for_testing()
    user_id = str(uuid4())
    tool_name = "delete_task"
    target_id = str(uuid4())
    action = "delete"

    # 1. Issue challenge
    token = ConfirmationService.issue_challenge(
        user_id=user_id,
        tool_name=tool_name,
        target_id=target_id,
        action=action,
        ttl_seconds=300
    )

    assert isinstance(token, str)
    assert "." in token

    # 2. Consume challenge with valid matching parameters
    is_valid = ConfirmationService.verify_and_consume(
        token=token,
        user_id=user_id,
        tool_name=tool_name,
        target_id=target_id,
        action=action
    )
    assert is_valid is True

    # 3. Replay attack: second consumption MUST fail (single-use)
    replay_attempt = ConfirmationService.verify_and_consume(
        token=token,
        user_id=user_id,
        tool_name=tool_name,
        target_id=target_id,
        action=action
    )
    assert replay_attempt is False


def test_confirmation_service_tampered_token_rejected():
    """Verify tampering with payload or signature results in rejection."""
    ConfirmationService.reset_consumed_tokens_for_testing()
    user_id = str(uuid4())
    target_id = str(uuid4())

    token = ConfirmationService.issue_challenge(
        user_id=user_id,
        tool_name="delete_task",
        target_id=target_id,
        action="delete"
    )

    parts = token.split(".")
    assert len(parts) == 2
    payload_b64, sig_b64 = parts

    # 1. Tamper with signature
    tampered_sig = sig_b64[:-2] + "xx"
    assert ConfirmationService.verify_and_consume(
        token=f"{payload_b64}.{tampered_sig}",
        user_id=user_id,
        tool_name="delete_task",
        target_id=target_id,
        action="delete"
    ) is False

    # 2. Tamper with payload
    tampered_payload = payload_b64[:-2] + "yy"
    assert ConfirmationService.verify_and_consume(
        token=f"{tampered_payload}.{sig_b64}",
        user_id=user_id,
        tool_name="delete_task",
        target_id=target_id,
        action="delete"
    ) is False

    # 3. Completely bogus token
    assert ConfirmationService.verify_and_consume(
        token="completely_bogus_token_without_period",
        user_id=user_id,
        tool_name="delete_task",
        target_id=target_id,
        action="delete"
    ) is False


def test_confirmation_service_expired_token_rejected():
    """Verify challenge token past TTL is rejected."""
    ConfirmationService.reset_consumed_tokens_for_testing()
    user_id = str(uuid4())
    target_id = str(uuid4())

    # Issue token with -1 TTL (already expired)
    token = ConfirmationService.issue_challenge(
        user_id=user_id,
        tool_name="delete_task",
        target_id=target_id,
        action="delete",
        ttl_seconds=-1
    )

    res = ConfirmationService.verify_and_consume(
        token=token,
        user_id=user_id,
        tool_name="delete_task",
        target_id=target_id,
        action="delete"
    )
    assert res is False


def test_confirmation_service_cross_binding_rejection():
    """Verify tokens are strictly bound to user, tool, target, and action."""
    ConfirmationService.reset_consumed_tokens_for_testing()
    user_a = str(uuid4())
    user_b = str(uuid4())
    task_1 = str(uuid4())
    task_2 = str(uuid4())

    token = ConfirmationService.issue_challenge(
        user_id=user_a,
        tool_name="delete_task",
        target_id=task_1,
        action="delete"
    )

    # Cross-user attempt
    assert ConfirmationService.verify_and_consume(
        token=token,
        user_id=user_b,
        tool_name="delete_task",
        target_id=task_1,
        action="delete"
    ) is False

    # Cross-tool attempt
    assert ConfirmationService.verify_and_consume(
        token=token,
        user_id=user_a,
        tool_name="delete_reminder",
        target_id=task_1,
        action="delete"
    ) is False

    # Cross-target attempt
    assert ConfirmationService.verify_and_consume(
        token=token,
        user_id=user_a,
        tool_name="delete_task",
        target_id=task_2,
        action="delete"
    ) is False


@pytest.mark.asyncio
async def test_tool_executor_intercepts_high_risk_actions(test_db: AsyncSession):
    """Verify ToolExecutor stops HIGH_RISK_WRITE tools without token and generates challenge."""
    ConfirmationService.reset_consumed_tokens_for_testing()
    test_user = await create_test_user(test_db, "executor_user@example.com")

    # Seed a task to delete
    task = Task(
        user_id=test_user.id,
        title="Task Requiring Confirmation",
        status="pending",
        priority="medium"
    )
    test_db.add(task)
    await test_db.commit()
    await test_db.refresh(task)

    # 1. Calling delete_task without confirmation token MUST return confirmation_required
    result = await ToolExecutor.execute_tool(
        user_id=test_user.id,
        db=test_db,
        tool_name="delete_task",
        arguments={"task_id": task.id},
    )

    assert result.status == "confirmation_required"
    assert result.confirmation_challenge is not None
    assert result.confirmation_challenge.target_id == task.id
    assert result.confirmation_challenge.tool == "delete_task"
    assert result.confirmation_challenge.confirmation_token is not None

    # 2. Forged booleans (e.g. confirmed: True) MUST be rejected / still require cryptographic token
    forged_result = await ToolExecutor.execute_tool(
        user_id=test_user.id,
        db=test_db,
        tool_name="delete_task",
        arguments={"task_id": task.id, "confirmed": True, "force": True},
        confirmation_token=None
    )
    assert forged_result.status == "confirmation_required"
    assert forged_result.confirmation_challenge is not None

    # 3. Calling with valid confirmation token executes cleanly
    valid_token = result.confirmation_challenge.confirmation_token
    confirmed_result = await ToolExecutor.execute_tool(
        user_id=test_user.id,
        db=test_db,
        tool_name="delete_task",
        arguments={"task_id": task.id},
        confirmation_token=valid_token
    )

    assert confirmed_result.status == "completed"
    assert confirmed_result.is_error is False
    assert confirmed_result.result_payload["status"] == "success"


@pytest.mark.asyncio
async def test_tool_executor_reminder_deletion_confirmation(test_db: AsyncSession):
    """Verify ToolExecutor intercepts delete_reminder for confirmation."""
    ConfirmationService.reset_consumed_tokens_for_testing()
    test_user = await create_test_user(test_db, "executor_rem_user@example.com")

    # Seed a reminder
    reminder = Reminder(
        user_id=test_user.id,
        title="Reminder To Confirm Delete",
        remind_at=datetime.now(timezone.utc),
        timezone="UTC",
        status="scheduled"
    )
    test_db.add(reminder)
    await test_db.commit()
    await test_db.refresh(reminder)

    # 1. Unconfirmed attempt
    res = await ToolExecutor.execute_tool(
        user_id=test_user.id,
        db=test_db,
        tool_name="delete_reminder",
        arguments={"reminder_id": reminder.id},
    )
    assert res.status == "confirmation_required"
    assert res.confirmation_challenge is not None
    assert res.confirmation_challenge.confirmation_token is not None

    # 2. Confirmed attempt
    confirmed = await ToolExecutor.execute_tool(
        user_id=test_user.id,
        db=test_db,
        tool_name="delete_reminder",
        arguments={"reminder_id": reminder.id},
        confirmation_token=res.confirmation_challenge.confirmation_token
    )
    assert confirmed.status == "completed"
    assert confirmed.result_payload["status"] == "success"


@pytest.mark.asyncio
async def test_tool_executor_unknown_tool_rejection(test_db: AsyncSession):
    """Verify ToolExecutor handles unauthorized or unknown tool names safely."""
    test_user = await create_test_user(test_db, "unknown_tool_user@example.com")
    res = await ToolExecutor.execute_tool(
        user_id=test_user.id,
        db=test_db,
        tool_name="arbitrary_system_command",
        arguments={"cmd": "rm -rf /"}
    )
    assert res.status == "failed"
    assert res.is_error is True
    assert "not authorized" in res.result_payload["message"].lower()


@pytest.mark.asyncio
async def test_tool_executor_timeout_protection(test_db: AsyncSession):
    """Verify ToolExecutor bounds execution duration with timeout handler."""
    import asyncio
    test_user = await create_test_user(test_db, "timeout_user@example.com")

    # Temporarily patch a tool handler to hang
    async def hanging_tool(user_id, db, **kwargs):
        await asyncio.sleep(100)
        return {"status": "success"}

    with patch.object(ToolRegistry, "get") as mock_get:
        from app.ai.agent.tool_registry import ToolDefinition
        mock_get.return_value = ToolDefinition(
            name="hanging_tool",
            description="Hangs indefinitely",
            friendly_name="Hanging tool",
            risk_level=RiskLevel.READ,
            func=hanging_tool,
            parameters_schema={}
        )

        with patch("app.core.config.settings.TOOL_TIMEOUT_SECONDS", 0.05):
            res = await ToolExecutor.execute_tool(
                user_id=test_user.id,
                db=test_db,
                tool_name="hanging_tool",
                arguments={}
            )
            assert res.status == "failed"
            assert res.is_error is True
            assert "timed out" in res.result_payload["message"].lower()


def test_confirmation_service_wrong_action_fails():
    """Verify challenge issued for action A cannot be verified for action B."""
    token = ConfirmationService.issue_challenge(
        user_id="user_action_test",
        tool_name="delete_task",
        target_id="task_123",
        action="delete"
    )
    
    # Try verifying with different action 'update'
    is_valid = ConfirmationService.verify_and_consume(
        token=token,
        user_id="user_action_test",
        tool_name="delete_task",
        target_id="task_123",
        action="update"
    )
    assert is_valid is False


def test_confirmation_service_empty_token_fails():
    """Verify empty or None tokens are safely rejected."""
    assert ConfirmationService.verify_and_consume("", "u1", "delete_task", "t1", "delete") is False
    assert ConfirmationService.verify_and_consume(None, "u1", "delete_task", "t1", "delete") is False


def test_confirmation_service_tampered_base64_structure():
    """Verify malformed base64 strings fail validation safely."""
    assert ConfirmationService.verify_and_consume("not-valid-base64-payload.signature", "u1", "delete_task", "t1", "delete") is False
    assert ConfirmationService.verify_and_consume("invalid_token_without_dot", "u1", "delete_task", "t1", "delete") is False


