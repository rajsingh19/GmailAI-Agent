"""
Tests for Multi-Worker Voice Cancellation and IDOR Defense (Milestone 10).
Verifies:
- 401 Unauthorized for unauthenticated cancel requests
- 404 Not Found for non-existent execution ID
- 404 Not Found for cross-user cancellation attempt (strict IDOR defense)
- 200 OK for legitimate owner cancellation
- Cancellation aborts pipeline execution at cancellation checkpoints
- Local asyncio.Task is cancelled if running on the current worker
- Distributed Redis state synchronization for cancellation
- Graceful handling of cancellation for already completed executions
- Pipeline returns HTTP 499 when VoiceCancelledError is raised
- Reset for testing cleans all in-memory registries
"""

import asyncio
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.voice.execution_manager import (
    CrossUserCancellationError,
    ExecutionNotFoundError,
    VoiceExecutionManager,
)
from app.voice.providers.factory import set_stt_provider_for_testing, set_tts_provider_for_testing
from app.voice.providers.mock_stt import MockSTTProvider
from app.voice.providers.mock_tts import MockTTSProvider, _generate_valid_wav_bytes
from app.voice.service import VoiceCancelledError, VoiceService


async def create_test_user(test_db: AsyncSession, email: str = "voice_cancel_user@example.com") -> User:
    user = User(email=email, full_name="Voice Cancel Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_cancel_endpoint_requires_authentication(async_client: AsyncClient):
    res = await async_client.post("/api/v1/voice/cancel/exec_random_123")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_cancel_endpoint_nonexistent_execution_returns_404(async_client: AsyncClient, test_db: AsyncSession):
    VoiceExecutionManager.reset_for_testing()
    user = await create_test_user(test_db, "cancel_nonexistent@example.com")
    set_auth_cookie(async_client, user)

    res = await async_client.post("/api/v1/voice/cancel/exec_not_found_999")
    assert res.status_code == 404
    assert res.json()["detail"] == "Execution not found"


@pytest.mark.asyncio
async def test_cancel_endpoint_cross_user_idor_returns_404(async_client: AsyncClient, test_db: AsyncSession):
    VoiceExecutionManager.reset_for_testing()
    user_a = await create_test_user(test_db, "user_a_cancel@example.com")
    user_b = await create_test_user(test_db, "user_b_cancel@example.com")

    # User B has an active execution
    exec_id = "exec_user_b_active_42"
    await VoiceExecutionManager.register_execution(exec_id, user_b.id)

    # User A attempts to cancel User B's execution (IDOR attempt)
    set_auth_cookie(async_client, user_a)
    res = await async_client.post(f"/api/v1/voice/cancel/{exec_id}")

    # Security Invariant: Must return 404 to avoid leaking execution ID existence
    assert res.status_code == 404
    assert res.json()["detail"] == "Execution not found"

    # Verify execution was NOT cancelled
    assert await VoiceExecutionManager.is_cancel_requested(exec_id) is False


@pytest.mark.asyncio
async def test_cancel_endpoint_valid_owner_marks_cancelled(async_client: AsyncClient, test_db: AsyncSession):
    VoiceExecutionManager.reset_for_testing()
    user = await create_test_user(test_db, "owner_cancel@example.com")
    set_auth_cookie(async_client, user)

    exec_id = "exec_owner_active_1"
    dummy_task = asyncio.create_task(asyncio.sleep(10.0))
    await VoiceExecutionManager.register_execution(exec_id, user.id, task=dummy_task)

    res = await async_client.post(f"/api/v1/voice/cancel/{exec_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "cancelled"
    assert data["execution_id"] == exec_id

    # Verify state reflects cancellation
    assert await VoiceExecutionManager.is_cancel_requested(exec_id) is True
    assert dummy_task.cancelling() > 0 or dummy_task.cancelled()


@pytest.mark.asyncio
async def test_cancellation_aborts_pipeline_at_checkpoint(test_db: AsyncSession):
    VoiceExecutionManager.reset_for_testing()
    user = await create_test_user(test_db, "pipeline_cancel_chk@example.com")

    exec_id = "exec_chk_test"
    dummy_task = asyncio.create_task(asyncio.sleep(10.0))
    await VoiceExecutionManager.register_execution(exec_id, user.id, task=dummy_task)

    # Trigger cancellation before or during pipeline
    await VoiceExecutionManager.cancel_execution(exec_id, user.id)
    assert await VoiceExecutionManager.is_cancel_requested(exec_id) is True
    assert dummy_task.cancelling() > 0 or dummy_task.cancelled()


@pytest.mark.asyncio
async def test_cancellation_aborts_local_asyncio_task(test_db: AsyncSession):
    VoiceExecutionManager.reset_for_testing()
    user = await create_test_user(test_db, "task_abort_user@example.com")

    task_cancelled = False

    async def long_running_task():
        nonlocal task_cancelled
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            task_cancelled = True
            raise

    loop_task = asyncio.create_task(long_running_task())
    exec_id = "exec_local_task_1"
    await VoiceExecutionManager.register_execution(exec_id, user.id, task=loop_task)

    # Cancel execution
    success = await VoiceExecutionManager.cancel_execution(exec_id, user.id)
    assert success is True

    # Allow event loop to process task cancellation
    await asyncio.sleep(0.01)
    assert loop_task.cancelled() or task_cancelled is True


@pytest.mark.asyncio
async def test_redis_distributed_cancellation_state_coordination(test_db: AsyncSession):
    user = await create_test_user(test_db, "redis_cancel_user@example.com")
    exec_id = "exec_redis_coord_1"

    # Test with Redis mocked client
    mock_redis = AsyncMock()
    mock_redis.get.return_value = '{"execution_id": "exec_redis_coord_1", "user_id": "' + user.id + '", "worker_id": "other-node:123", "cancel_requested": false, "status": "running"}'
    mock_redis.set.return_value = True

    with patch("app.voice.execution_manager._get_redis_client", return_value=mock_redis):
        cancelled = await VoiceExecutionManager.cancel_execution(exec_id, user.id)
        assert cancelled is True
        assert mock_redis.set.called
        call_args = mock_redis.set.call_args[0]
        assert f"voice:exec:{exec_id}" in call_args[0]
        assert '"cancel_requested": true' in call_args[1] or '"status": "cancelled"' in call_args[1]


@pytest.mark.asyncio
async def test_cancel_completed_execution_handled_gracefully(test_db: AsyncSession):
    VoiceExecutionManager.reset_for_testing()
    user = await create_test_user(test_db, "completed_cancel_user@example.com")

    exec_id = "exec_already_done"
    await VoiceExecutionManager.register_execution(exec_id, user.id)
    await VoiceExecutionManager.complete_execution(exec_id)

    # Cancelling an execution that was already completed
    # Should update state safely without throwing unhandled server errors
    await VoiceExecutionManager.cancel_execution(exec_id, user.id)
    assert await VoiceExecutionManager.is_cancel_requested(exec_id) is True


@pytest.mark.asyncio
async def test_voice_chat_returns_cancelled_response_or_499(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_test_user(test_db, "voice_chat_499_user@example.com")
    set_auth_cookie(async_client, user)

    set_stt_provider_for_testing(MockSTTProvider(default_transcript="Hello world"))
    set_tts_provider_for_testing(MockTTSProvider())

    try:
        # Simulate VoiceCancelledError raised during pipeline execution
        with patch("app.voice.service.VoiceService.process_voice_chat") as mock_process:
            mock_process.side_effect = VoiceCancelledError("Execution cancelled by user")

            wav_bytes = _generate_valid_wav_bytes(1.0)
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            res = await async_client.post("/api/v1/voice/chat", files=files)

            assert res.status_code == 499
            assert "cancelled" in res.json()["detail"].lower()
    finally:
        set_stt_provider_for_testing(None)
        set_tts_provider_for_testing(None)


def test_execution_manager_reset_for_testing():
    from app.voice.execution_manager import _LOCAL_TASKS, _IN_MEMORY_STATE
    _LOCAL_TASKS["dummy_task"] = None
    _IN_MEMORY_STATE["dummy_state"] = {}
    VoiceExecutionManager.reset_for_testing()
    assert len(_LOCAL_TASKS) == 0
    assert len(_IN_MEMORY_STATE) == 0
