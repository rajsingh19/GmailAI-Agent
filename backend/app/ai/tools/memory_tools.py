"""
Personal Memory & Long-Term Preference AI Tools (Milestone 11).
Registers 7 memory management tools into the static ToolRegistry whitelist:
- 3 READ tools (search_memories, list_memories, get_memory)
- 3 LOW_RISK_WRITE tools (create_memory, update_memory, deactivate_memory)
- 1 HIGH_RISK_WRITE tool (delete_memory, requires M6 cryptographic confirmation challenge)
"""
import logging
from typing import Dict, Any, Optional, Literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolRegistry, ToolDefinition, RiskLevel
from app.schemas.memory import MemoryCreateRequest, MemoryUpdateRequest

logger = logging.getLogger(__name__)


async def execute_search_memories(
    user_id: str,
    db: AsyncSession,
    query: str,
    category: Optional[str] = None,
    limit: Optional[int] = 10,
) -> Dict[str, Any]:
    """Tool function to search personal memories and preferences."""
    from app.services.memory_service import MemoryService
    try:
        lim = min(max(limit or 10, 1), 20)
        memories = await MemoryService.search_memories(
            db=db,
            user_id=user_id,
            query=query,
            category=category,
            limit=lim,
        )
        items = [
            {
                "id": m.id,
                "category": m.category,
                "key": m.key,
                "value": m.value,
                "confidence": m.confidence,
                "explicitly_confirmed": m.explicitly_confirmed,
                "active": m.active,
            }
            for m in memories
        ]
        return {
            "status": "success",
            "count": len(items),
            "memories": items,
        }
    except Exception as exc:
        logger.exception("Error in execute_search_memories: %s", exc)
        return {"status": "error", "message": f"Failed to search memories: {str(exc)}"}


async def execute_list_memories(
    user_id: str,
    db: AsyncSession,
    category: Optional[str] = None,
    active: Optional[bool] = True,
    limit: Optional[int] = 10,
) -> Dict[str, Any]:
    """Tool function to list personal memories and preferences."""
    from app.services.memory_service import MemoryService
    try:
        lim = min(max(limit or 10, 1), 20)
        items, total = await MemoryService.list_memories(
            db=db,
            user_id=user_id,
            category=category,
            active=active,
            limit=lim,
            offset=0,
        )
        return {
            "status": "success",
            "total": total,
            "count": len(items),
            "memories": [
                {
                    "id": m.id,
                    "category": m.category,
                    "key": m.key,
                    "value": m.value,
                    "confidence": m.confidence,
                    "active": m.active,
                }
                for m in items
            ],
        }
    except Exception as exc:
        logger.exception("Error in execute_list_memories: %s", exc)
        return {"status": "error", "message": f"Failed to list memories: {str(exc)}"}


async def execute_get_memory(
    user_id: str,
    db: AsyncSession,
    memory_id: str,
) -> Dict[str, Any]:
    """Tool function to retrieve details of a specific memory by ID."""
    from app.services.memory_service import MemoryService
    try:
        memory = await MemoryService.get_memory(db=db, user_id=user_id, memory_id=memory_id)
        if not memory:
            return {"status": "error", "message": f"Memory with ID '{memory_id}' not found."}
        return {
            "status": "success",
            "memory": {
                "id": memory.id,
                "category": memory.category,
                "key": memory.key,
                "value": memory.value,
                "description": memory.description,
                "confidence": memory.confidence,
                "source": memory.source,
                "explicitly_confirmed": memory.explicitly_confirmed,
                "active": memory.active,
                "last_confirmed_at": memory.last_confirmed_at.isoformat(),
            },
        }
    except Exception as exc:
        logger.exception("Error in execute_get_memory: %s", exc)
        return {"status": "error", "message": f"Failed to get memory: {str(exc)}"}


async def execute_create_memory(
    user_id: str,
    db: AsyncSession,
    category: str,
    key: str,
    value: str,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Tool function to explicitly save a user preference or fact."""
    from app.services.memory_service import MemoryService, SecretDetectedError
    # Check if memory feature is enabled
    enabled = await MemoryService.is_memory_enabled_for_user(db=db, user_id=user_id)
    if not enabled:
        return {
            "status": "error",
            "message": "Long-term memory is currently disabled. Please enable Personal Memory in settings to save preferences.",
        }

    try:
        memory_in = MemoryCreateRequest(
            category=category,  # type: ignore
            key=key,
            value=value,
            description=description,
            confidence="EXPLICIT",
            source="explicit_user_request",
            explicitly_confirmed=True,
        )
        memory = await MemoryService.create_or_upsert_memory(db=db, user_id=user_id, memory_in=memory_in)
        return {
            "status": "success",
            "message": f"Remembered: {memory.key} = '{memory.value}'",
            "memory": {
                "id": memory.id,
                "category": memory.category,
                "key": memory.key,
                "value": memory.value,
                "confidence": memory.confidence,
                "active": memory.active,
            },
        }
    except SecretDetectedError as sde:
        return {"status": "error", "message": str(sde)}
    except Exception as exc:
        logger.exception("Error in execute_create_memory: %s", exc)
        return {"status": "error", "message": f"Failed to save memory: {str(exc)}"}


async def execute_update_memory(
    user_id: str,
    db: AsyncSession,
    memory_id: str,
    value: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Tool function to update an existing memory."""
    from app.services.memory_service import MemoryService, SecretDetectedError
    try:
        update_in = MemoryUpdateRequest(
            value=value,
            description=description,
            category=category,  # type: ignore
            explicitly_confirmed=True,
            confidence="EXPLICIT",
        )
        memory = await MemoryService.update_memory(db=db, user_id=user_id, memory_id=memory_id, update_in=update_in)
        if not memory:
            return {"status": "error", "message": f"Memory with ID '{memory_id}' not found."}
        return {
            "status": "success",
            "message": f"Updated memory '{memory.key}'.",
            "memory": {
                "id": memory.id,
                "category": memory.category,
                "key": memory.key,
                "value": memory.value,
            },
        }
    except SecretDetectedError as sde:
        return {"status": "error", "message": str(sde)}
    except Exception as exc:
        logger.exception("Error in execute_update_memory: %s", exc)
        return {"status": "error", "message": f"Failed to update memory: {str(exc)}"}


async def execute_deactivate_memory(
    user_id: str,
    db: AsyncSession,
    memory_id: str,
) -> Dict[str, Any]:
    """Tool function to soft-deactivate a memory."""
    from app.services.memory_service import MemoryService
    try:
        memory = await MemoryService.deactivate_memory(db=db, user_id=user_id, memory_id=memory_id)
        if not memory:
            return {"status": "error", "message": f"Memory with ID '{memory_id}' not found."}
        return {
            "status": "success",
            "message": f"Deactivated memory '{memory.key}'. It will no longer be used for personalization.",
            "memory_id": memory.id,
        }
    except Exception as exc:
        logger.exception("Error in execute_deactivate_memory: %s", exc)
        return {"status": "error", "message": f"Failed to deactivate memory: {str(exc)}"}


async def execute_delete_memory(
    user_id: str,
    db: AsyncSession,
    memory_id: str,
) -> Dict[str, Any]:
    """Tool function to permanently delete a memory (HIGH RISK - requires M6 confirmation token)."""
    from app.services.memory_service import MemoryService
    try:
        deleted = await MemoryService.delete_memory(db=db, user_id=user_id, memory_id=memory_id)
        if not deleted:
            return {"status": "error", "message": f"Memory with ID '{memory_id}' not found."}
        return {
            "status": "success",
            "message": f"Memory with ID '{memory_id}' has been permanently deleted.",
            "memory_id": memory_id,
        }
    except Exception as exc:
        logger.exception("Error in execute_delete_memory: %s", exc)
        return {"status": "error", "message": f"Failed to delete memory: {str(exc)}"}


def register_memory_tools() -> None:
    """Registers all 7 long-term memory tools into the static ToolRegistry whitelist."""
    # 1. search_memories
    ToolRegistry.register(
        ToolDefinition(
            name="search_memories",
            description="Search your long-term preferences, facts, and project context by query or category.",
            friendly_name="Searching personal memory",
            risk_level=RiskLevel.READ,
            func=execute_search_memories,
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query terms to find relevant memories"},
                    "category": {
                        "type": "string",
                        "enum": ["user_preference", "user_fact", "project_context", "workflow_preference", "explicit_user_memory"],
                        "description": "Optional category filter",
                    },
                    "limit": {"type": "integer", "description": "Max results to return (default 10, max 20)"},
                },
                "required": ["query"],
            },
        )
    )

    # 2. list_memories
    ToolRegistry.register(
        ToolDefinition(
            name="list_memories",
            description="List your stored preferences, habits, facts, and project context.",
            friendly_name="Listing personal memories",
            risk_level=RiskLevel.READ,
            func=execute_list_memories,
            parameters_schema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["user_preference", "user_fact", "project_context", "workflow_preference", "explicit_user_memory"],
                        "description": "Optional category filter",
                    },
                    "active": {"type": "boolean", "description": "Filter by active status (default True)"},
                    "limit": {"type": "integer", "description": "Max items to return (default 10)"},
                },
            },
        )
    )

    # 3. get_memory
    ToolRegistry.register(
        ToolDefinition(
            name="get_memory",
            description="Retrieve detailed information about a specific memory by unique ID.",
            friendly_name="Fetching memory details",
            risk_level=RiskLevel.READ,
            func=execute_get_memory,
            parameters_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Unique ID of the memory"},
                },
                "required": ["memory_id"],
            },
        )
    )

    # 4. create_memory
    ToolRegistry.register(
        ToolDefinition(
            name="create_memory",
            description="Explicitly remember a user preference, personal fact, project context, or workflow habit.",
            friendly_name="Remembering preference",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_create_memory,
            parameters_schema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["user_preference", "user_fact", "project_context", "workflow_preference", "explicit_user_memory"],
                        "description": "Classification category for the memory",
                    },
                    "key": {"type": "string", "description": "Normalized identifier (e.g. 'coding.language', 'framework.backend')"},
                    "value": {"type": "string", "description": "The exact preference or fact to remember"},
                    "description": {"type": "string", "description": "Optional details or context"},
                },
                "required": ["category", "key", "value"],
            },
        )
    )

    # 5. update_memory
    ToolRegistry.register(
        ToolDefinition(
            name="update_memory",
            description="Update the value or description of an existing remembered preference or fact.",
            friendly_name="Updating memory",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_update_memory,
            parameters_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "ID of the memory to update"},
                    "value": {"type": "string", "description": "Updated preference value"},
                    "description": {"type": "string", "description": "Updated description"},
                    "category": {
                        "type": "string",
                        "enum": ["user_preference", "user_fact", "project_context", "workflow_preference", "explicit_user_memory"],
                        "description": "Updated category",
                    },
                },
                "required": ["memory_id"],
            },
        )
    )

    # 6. deactivate_memory
    ToolRegistry.register(
        ToolDefinition(
            name="deactivate_memory",
            description="Soft-deactivate a memory so it is no longer used for personalization, without deleting history.",
            friendly_name="Deactivating memory",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_deactivate_memory,
            parameters_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "ID of the memory to deactivate"},
                },
                "required": ["memory_id"],
            },
        )
    )

    # 7. delete_memory
    ToolRegistry.register(
        ToolDefinition(
            name="delete_memory",
            description="Permanently delete a remembered preference or fact. HIGH RISK: Requires explicit confirmation challenge token.",
            friendly_name="Deleting memory",
            risk_level=RiskLevel.HIGH_RISK_WRITE,
            target_id_param="memory_id",
            func=execute_delete_memory,
            parameters_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "ID of the memory to permanently delete"},
                },
                "required": ["memory_id"],
            },
        )
    )
