"""
M8 scheduler advisory lock and idempotency regression tests.
Verifies that M9 production hardening, database pool, and middleware
have not altered or regressed M8 distributed scheduler locking (84920184)
and notification idempotency.
"""
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.models.notification import Notification
from app.services.notification_service import NotificationService
from app.services.proactive.monitor_service import (
    PROACTIVE_ADVISORY_LOCK_ID,
    ProactiveMonitorService,
)


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def test_advisory_lock_constant_is_preserved():
    """Asserts that the advisory lock ID is strictly preserved as 84920184."""
    assert PROACTIVE_ADVISORY_LOCK_ID == 84920184


@pytest.mark.asyncio
async def test_advisory_lock_prevents_concurrent_runs_on_postgresql():
    """
    Simulates another worker process already holding the advisory lock.
    Verifies that run_proactive_cycle immediately skips execution.
    """
    service = ProactiveMonitorService()

    mock_session = AsyncMock()
    mock_session.bind = MagicMock()
    mock_session.bind.dialect.name = "postgresql"
    mock_res = MagicMock()
    mock_res.scalar.return_value = False  # Lock acquisition failed
    mock_session.execute.return_value = mock_res

    with patch(
        "app.services.proactive.monitor_service.AsyncSessionLocal",
        return_value=FakeSessionContext(mock_session),
    ):
        stats = await service.run_proactive_cycle()
        assert stats.get("skipped_due_to_lock") is True
        assert stats["users_processed"] == 0


@pytest.mark.asyncio
async def test_advisory_lock_released_in_finally_on_success():
    """
    Verifies that when a worker acquires the advisory lock,
    pg_advisory_unlock is strictly called in the finally block.
    """
    service = ProactiveMonitorService()

    mock_session = AsyncMock()
    mock_session.bind = MagicMock()
    mock_session.bind.dialect.name = "postgresql"

    async def fake_execute(stmt, params=None):
        m = MagicMock()
        stmt_str = str(stmt)
        if "pg_try_advisory_lock" in stmt_str:
            m.scalar.return_value = True  # Successfully acquired
            return m
        elif "pg_advisory_unlock" in stmt_str:
            m.scalar.return_value = True
            return m
        else:
            # Users query
            m.scalars.return_value.all.return_value = []
            return m

    mock_session.execute.side_effect = fake_execute

    with patch(
        "app.services.proactive.monitor_service.AsyncSessionLocal",
        return_value=FakeSessionContext(mock_session),
    ):
        stats = await service.run_proactive_cycle()
        assert stats.get("skipped_due_to_lock") is not True

        # Check that pg_advisory_unlock was executed
        executed_stmts = [str(call.args[0]) for call in mock_session.execute.call_args_list if call.args]
        unlock_calls = [s for s in executed_stmts if "pg_advisory_unlock" in s]
        assert len(unlock_calls) >= 1


@pytest.mark.asyncio
async def test_advisory_lock_released_in_finally_on_exception():
    """
    Verifies that even if an unexpected error occurs during cycle execution,
    pg_advisory_unlock is unconditionally executed in the finally block.
    """
    service = ProactiveMonitorService()

    mock_session = AsyncMock()
    mock_session.bind = MagicMock()
    mock_session.bind.dialect.name = "postgresql"

    async def fake_execute(stmt, params=None):
        stmt_str = str(stmt)
        if "pg_try_advisory_lock" in stmt_str:
            m = MagicMock()
            m.scalar.return_value = True
            return m
        elif "pg_advisory_unlock" in stmt_str:
            m = MagicMock()
            m.scalar.return_value = True
            return m
        else:
            raise RuntimeError("Database exploded during user fetch")

    mock_session.execute.side_effect = fake_execute

    with patch(
        "app.services.proactive.monitor_service.AsyncSessionLocal",
        return_value=FakeSessionContext(mock_session),
    ):
        with pytest.raises(RuntimeError, match="Database exploded"):
            await service.run_proactive_cycle()

        # Unlock must still have been called
        executed_stmts = [str(call.args[0]) for call in mock_session.execute.call_args_list if call.args]
        unlock_calls = [s for s in executed_stmts if "pg_advisory_unlock" in s]
        assert len(unlock_calls) >= 1


@pytest.mark.asyncio
async def test_m8_notification_idempotency_key_constraint(test_db):
    """
    Verifies that UNIQUE(user_id, idempotency_key) prevents duplicate notification creation
    and returns None or the existing notification.
    """
    user_id = "test-user-m8-reg"
    idempotency_key = "unique-key-12345"

    notif1 = await NotificationService.create_notification(
        db=test_db,
        user_id=user_id,
        idempotency_key=idempotency_key,
        title="Test Notification 1",
        message="Message 1",
        notification_type="task_due",
        priority="high",
        source_type="task",
    )
    assert notif1 is not None
    assert notif1.idempotency_key == idempotency_key

    # Attempt second notification with identical user_id and idempotency_key
    notif2 = await NotificationService.create_notification(
        db=test_db,
        user_id=user_id,
        idempotency_key=idempotency_key,
        title="Test Notification 2 (Duplicate)",
        message="Message 2",
        notification_type="task_due",
        priority="high",
        source_type="task",
    )
    # Service must recognize duplicate idempotency key and return existing or None without crashing
    assert notif2 is None or notif2.id == notif1.id


@pytest.mark.asyncio
async def test_m8_proactive_cycle_runs_safely_under_m9_stack():
    """
    Verifies that run_proactive_cycle runs without error under the current M9 stack
    and returns the expected dictionary contract.
    """
    service = ProactiveMonitorService()
    stats = await service.run_proactive_cycle()
    assert "started_at" in stats
    assert "users_processed" in stats
    assert "total_notifications_created" in stats
    assert "global_llm_calls_used" in stats
    assert "errors" in stats
    assert stats["errors"] == 0
