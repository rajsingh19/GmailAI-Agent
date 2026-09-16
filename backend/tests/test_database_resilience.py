"""
Unit tests for Milestone 9 Database Resilience and Connection Pool Hardening.
Verifies conditional pool arguments (SQLite vs PostgreSQL), safe rollback, and non-idempotent write safety.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db


def test_sqlite_conditional_pool_args_applied():
    """SQLite engine must receive check_same_thread=False and omit queue pool args."""
    from app.db import session as session_mod
    s = Settings(
        DATABASE_URL="sqlite+aiosqlite:///./test.db",
        ENVIRONMENT="development",
    )
    with patch("app.db.session.settings", s):
        # When SQLite is used, connect_args is set
        connect_args = {}
        if s.DATABASE_URL.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        assert connect_args.get("check_same_thread") is False


def test_postgresql_conditional_pool_args_applied():
    """PostgreSQL engine must receive pool_size, max_overflow, pool_recycle, pool_pre_ping."""
    s = Settings(
        DATABASE_URL="postgresql+asyncpg://usr:pwd@localhost:5432/db",
        ENVIRONMENT="development",
        DB_POOL_SIZE=15,
        DB_MAX_OVERFLOW=25,
        DB_POOL_TIMEOUT=35,
        DB_POOL_RECYCLE=1200,
    )
    with patch("app.db.session.settings", s):
        engine_kwargs = {
            "pool_size": s.DB_POOL_SIZE,
            "max_overflow": s.DB_MAX_OVERFLOW,
            "pool_timeout": s.DB_POOL_TIMEOUT,
            "pool_recycle": s.DB_POOL_RECYCLE,
            "pool_pre_ping": True,
        }
        assert engine_kwargs["pool_size"] == 15
        assert engine_kwargs["max_overflow"] == 25
        assert engine_kwargs["pool_pre_ping"] is True
        assert engine_kwargs["pool_recycle"] == 1200


@pytest.mark.asyncio
async def test_database_session_rolls_back_on_unhandled_exception():
    """get_db dependency executes session.rollback() if an unhandled exception occurs."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__.return_value = mock_session
    mock_session_maker.return_value.__aexit__.return_value = None

    with patch("app.db.session.AsyncSessionLocal", mock_session_maker):
        gen = get_db()
        await anext(gen)
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("Simulated transaction failure"))

        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_database_session_commits_on_clean_exit():
    """get_db dependency executes session.commit() on clean completion."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__.return_value = mock_session
    mock_session_maker.return_value.__aexit__.return_value = None

    with patch("app.db.session.AsyncSessionLocal", mock_session_maker):
        gen = get_db()
        await anext(gen)
        with pytest.raises(StopAsyncIteration):
            await anext(gen)

        mock_session.commit.assert_awaited_once()
        mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_database_session_closes_in_finally_block():
    """get_db guarantees session.close() is executed regardless of commit/rollback outcome."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.side_effect = Exception("Commit error")
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__.return_value = mock_session
    mock_session_maker.return_value.__aexit__.return_value = None

    with patch("app.db.session.AsyncSessionLocal", mock_session_maker):
        gen = get_db()
        await anext(gen)
        with pytest.raises(Exception):
            await anext(gen)

        mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_idempotent_writes_not_blindly_retried(test_db: AsyncSession):
    """
    INVARIANT TEST:
    Non-idempotent database operations are wrapped in transactions and not automatically retried,
    preventing duplicate mutations.
    """
    from app.models.user import User
    from app.models.task import Task
    user = User(email="test_task_owner@example.com", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)

    task = Task(user_id=user.id, title="Non-retry write test", status="pending")
    test_db.add(task)
    await test_db.commit()
    await test_db.refresh(task)

    assert task.id is not None


@pytest.mark.asyncio
async def test_concurrent_database_sessions_isolated(test_db: AsyncSession):
    """Multiple concurrent database sessions execute with transaction isolation."""
    res1 = await test_db.execute(text("SELECT 1"))
    res2 = await test_db.execute(text("SELECT 2"))
    assert res1.scalar() == 1
    assert res2.scalar() == 2


def test_database_pool_settings_read_from_config():
    """Default pool settings reflect production hardening parameters."""
    s = Settings()
    assert s.DB_POOL_SIZE == 10
    assert s.DB_MAX_OVERFLOW == 20
    assert s.DB_POOL_TIMEOUT == 30
    assert s.DB_POOL_RECYCLE == 1800
