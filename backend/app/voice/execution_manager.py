"""
Multi-worker voice execution and cancellation coordinator.
Maintains distributed execution state in Redis for cross-worker cancellation
with process-local asyncio.Task abort and strict user-scoped IDOR protection.
"""
import asyncio
import json
import logging
import os
import socket
import uuid
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
from app.core.config import settings

logger = logging.getLogger(settings.PROJECT_NAME)

# Unique identifier for the current worker process
WORKER_ID: str = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"

# Process-local task registry for immediate coroutine cancellation
_LOCAL_TASKS: Dict[str, asyncio.Task] = {}

# In-memory execution state fallback for dev/test environments without Redis
_IN_MEMORY_STATE: Dict[str, Dict[str, Any]] = {}


class ExecutionNotFoundError(Exception):
    """Raised when execution ID is not found or expired."""
    pass


class CrossUserCancellationError(Exception):
    """Raised when a user attempts to cancel another user's execution (IDOR)."""
    pass


def _get_redis_client() -> Optional[aioredis.Redis]:
    """Returns an async Redis client if configured."""
    if settings.REDIS_URL:
        try:
            return aioredis.from_url(
                settings.REDIS_URL,
                socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
            )
        except Exception as exc:
            logger.warning("Could not initialize Redis client for voice execution manager: %s", exc)
    return None


class VoiceExecutionManager:
    """
    Coordinates active voice execution tracking and safe cancellation.
    Guarantees that cancellation requests are routed across worker processes,
    verified against requesting user identity, and abort downstream operations safely.
    """

    TTL_SECONDS: int = 120

    @classmethod
    async def register_execution(
        cls,
        execution_id: str,
        user_id: str,
        task: Optional[asyncio.Task] = None,
    ) -> None:
        """Registers a new in-flight voice execution in Redis and local registry."""
        record = {
            "execution_id": execution_id,
            "user_id": user_id,
            "worker_id": WORKER_ID,
            "status": "running",
            "cancel_requested": False,
        }

        # 1. Register process-local task if provided
        current_task = task or asyncio.current_task()
        if current_task:
            _LOCAL_TASKS[execution_id] = current_task

        # 2. Register shared Redis state
        client = _get_redis_client()
        if client:
            try:
                key = f"voice:exec:{execution_id}"
                await client.set(key, json.dumps(record), ex=cls.TTL_SECONDS)
                await client.aclose()
                return
            except Exception as exc:
                logger.warning("Failed to store voice execution state in Redis: %s", exc)

        # Fallback to in-memory state
        _IN_MEMORY_STATE[execution_id] = record

    @classmethod
    async def is_cancel_requested(cls, execution_id: str) -> bool:
        """
        Pipeline checkpoint: checks whether cancellation was requested for execution_id.
        """
        client = _get_redis_client()
        if client:
            try:
                key = f"voice:exec:{execution_id}"
                raw = await client.get(key)
                await client.aclose()
                if raw:
                    data = json.loads(raw)
                    return bool(data.get("cancel_requested", False))
            except Exception as exc:
                logger.warning("Error querying cancellation state in Redis: %s", exc)

        # Fallback to in-memory state
        if execution_id in _IN_MEMORY_STATE:
            return bool(_IN_MEMORY_STATE[execution_id].get("cancel_requested", False))

        return False

    @classmethod
    async def cancel_execution(cls, execution_id: str, requesting_user_id: str) -> bool:
        """
        Requests cancellation for an active voice execution.
        Security Invariant:
        Must verify that requesting_user_id owns the execution.
        If owned by another user, raises CrossUserCancellationError (HTTP 404 IDOR defense).
        """
        record: Optional[Dict[str, Any]] = None
        client = _get_redis_client()

        # 1. Fetch current execution record
        if client:
            try:
                key = f"voice:exec:{execution_id}"
                raw = await client.get(key)
                if raw:
                    record = json.loads(raw)
            except Exception as exc:
                logger.warning("Error fetching execution state from Redis during cancel: %s", exc)

        if not record:
            record = _IN_MEMORY_STATE.get(execution_id)

        if not record:
            raise ExecutionNotFoundError(f"Execution '{execution_id}' not found or has completed.")

        # 2. IDOR check: verify ownership
        if record.get("user_id") != requesting_user_id:
            logger.warning(
                "IDOR ATTEMPT: User '%s' attempted to cancel execution '%s' owned by user '%s'",
                requesting_user_id,
                execution_id,
                record.get("user_id"),
            )
            raise CrossUserCancellationError("Execution not found")

        # 3. Update state in Redis
        record["cancel_requested"] = True
        record["status"] = "cancelled"

        if client:
            try:
                key = f"voice:exec:{execution_id}"
                await client.set(key, json.dumps(record), ex=cls.TTL_SECONDS)
                await client.aclose()
            except Exception as exc:
                logger.warning("Failed to update cancellation state in Redis: %s", exc)

        _IN_MEMORY_STATE[execution_id] = record

        # 4. Abort local task if running in the current worker process
        if record.get("worker_id") == WORKER_ID and execution_id in _LOCAL_TASKS:
            task = _LOCAL_TASKS.get(execution_id)
            if task and not task.done():
                logger.info("[%s] Cancelling local asyncio.Task on worker %s", execution_id, WORKER_ID)
                task.cancel()

        return True

    @classmethod
    async def complete_execution(cls, execution_id: str) -> None:
        """Marks execution completed and cleans up local references."""
        _LOCAL_TASKS.pop(execution_id, None)

        client = _get_redis_client()
        if client:
            try:
                key = f"voice:exec:{execution_id}"
                raw = await client.get(key)
                if raw:
                    data = json.loads(raw)
                    data["status"] = "completed"
                    await client.set(key, json.dumps(data), ex=30)
                await client.aclose()
            except Exception as exc:
                logger.warning("Error marking execution completed in Redis: %s", exc)

        if execution_id in _IN_MEMORY_STATE:
            _IN_MEMORY_STATE[execution_id]["status"] = "completed"

    @classmethod
    def is_task_active(cls, execution_id: str) -> bool:
        """Returns whether execution_id is currently tracked as an active local task."""
        return execution_id in _LOCAL_TASKS

    @classmethod
    def reset_for_testing(cls) -> None:
        """Clears in-memory task and execution state between tests."""
        _LOCAL_TASKS.clear()
        _IN_MEMORY_STATE.clear()
