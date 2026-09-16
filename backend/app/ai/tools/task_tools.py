from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolDefinition, ToolRegistry, RiskLevel
from app.services.task_service import TaskService
from app.schemas.task import TaskCreate, TaskUpdate


async def execute_create_task(
    user_id: str,
    db: AsyncSession,
    title: str,
    description: Optional[str] = None,
    priority: Optional[str] = "medium",
    due_at: Optional[str] = None,
    user_timezone: Optional[str] = "UTC",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Tool function to create a new task for the authenticated user."""
    final_desc = description or kwargs.get("notes")
    due_dt = None
    if due_at:
        try:
            parsed = datetime.fromisoformat(due_at)
            due_dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return {"status": "error", "message": f"Invalid due_at ISO format: {due_at}"}

    tz_val = kwargs.get("timezone") or user_timezone or "UTC"
    task_in = TaskCreate(
        title=title,
        description=final_desc,
        priority=priority or "medium",
        due_at=due_dt,
        timezone=tz_val,
    )
    task = await TaskService.create_task(db=db, user_id=user_id, task_in=task_in)
    return {
        "status": "success",
        "task": {
            "id": task.id,
            "title": task.title,
            "priority": task.priority,
            "status": task.status,
            "due_at": task.due_at.isoformat() if task.due_at else None,
        },
    }


async def execute_list_tasks(
    user_id: str,
    db: AsyncSession,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: Optional[int] = 10,
) -> Dict[str, Any]:
    """Tool function to list tasks for the authenticated user."""
    lim = min(max(limit or 10, 1), 20)
    tasks, total = await TaskService.list_tasks(
        db=db, user_id=user_id, status=status, priority=priority, limit=lim, offset=0
    )
    items = [
        {
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "description": (t.description[:100] + "...") if t.description and len(t.description) > 100 else t.description,
        }
        for t in tasks
    ]
    return {
        "status": "success",
        "total": total,
        "count": len(items),
        "tasks": items,
    }


async def execute_get_task(
    user_id: str,
    db: AsyncSession,
    task_id: str,
) -> Dict[str, Any]:
    """Tool function to retrieve a specific task by ID."""
    task = await TaskService.get_task(db=db, user_id=user_id, task_id=task_id)
    if not task:
        return {"status": "error", "message": f"Task with ID '{task_id}' not found."}

    return {
        "status": "success",
        "task": {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        },
    }


async def execute_update_task(
    user_id: str,
    db: AsyncSession,
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    due_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Tool function to update an existing task."""
    due_dt = None
    if due_at:
        try:
            parsed = datetime.fromisoformat(due_at)
            due_dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return {"status": "error", "message": f"Invalid due_at ISO format: {due_at}"}

    update_data: Dict[str, Any] = {}
    if title is not None:
        update_data["title"] = title
    if description is not None:
        update_data["description"] = description
    if priority is not None:
        update_data["priority"] = priority
    if status is not None:
        update_data["status"] = status
    if due_dt is not None:
        update_data["due_at"] = due_dt

    update_in = TaskUpdate(**update_data)
    task = await TaskService.update_task(db=db, user_id=user_id, task_id=task_id, task_in=update_in)
    if not task:
        return {"status": "error", "message": f"Task with ID '{task_id}' not found."}

    return {
        "status": "success",
        "task": {
            "id": task.id,
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "due_at": task.due_at.isoformat() if task.due_at else None,
        },
    }


async def execute_complete_task(
    user_id: str,
    db: AsyncSession,
    task_id: str,
) -> Dict[str, Any]:
    """Tool function to mark a task as completed."""
    task = await TaskService.complete_task(db=db, user_id=user_id, task_id=task_id)
    if not task:
        return {"status": "error", "message": f"Task with ID '{task_id}' not found."}

    return {
        "status": "success",
        "message": f"Task '{task.title}' marked as completed.",
        "task_id": task.id,
    }


async def execute_delete_task(
    user_id: str,
    db: AsyncSession,
    task_id: str,
) -> Dict[str, Any]:
    """Tool function to delete a task. Classified as HIGH_RISK_WRITE."""
    deleted = await TaskService.delete_task(db=db, user_id=user_id, task_id=task_id)
    if not deleted:
        return {"status": "error", "message": f"Task with ID '{task_id}' not found."}

    return {
        "status": "success",
        "message": f"Task with ID '{task_id}' deleted successfully.",
        "task_id": task_id,
    }


def register_task_tools() -> None:
    """Registers all task management tools into the ToolRegistry."""
    ToolRegistry.register(
        ToolDefinition(
            name="create_task",
            description="Create a new task with title, priority (low, medium, high), and optional due date.",
            friendly_name="Creating task",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_create_task,
            parameters_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the task to create"},
                    "description": {"type": "string", "description": "Optional details or context"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Priority level"},
                    "due_at": {"type": "string", "description": "Timezone-aware ISO 8601 datetime string (e.g. '2026-09-16T10:00:00Z')"},
                    "timezone": {"type": "string", "description": "IANA timezone name (default 'UTC')"},
                },
                "required": ["title"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="list_tasks",
            description="List user tasks with optional filtering by status (pending, completed, cancelled) or priority.",
            friendly_name="Listing tasks",
            risk_level=RiskLevel.READ,
            func=execute_list_tasks,
            parameters_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["pending", "completed", "cancelled"], "description": "Filter by task status"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Filter by priority"},
                    "limit": {"type": "integer", "description": "Max number of tasks to return (default 10, max 20)"},
                },
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="get_task",
            description="Retrieve detailed information about a specific task by ID.",
            friendly_name="Fetching task details",
            risk_level=RiskLevel.READ,
            func=execute_get_task,
            parameters_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "The unique ID of the task"},
                },
                "required": ["task_id"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="update_task",
            description="Update title, description, priority, status, or due date of an existing task.",
            friendly_name="Updating task",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_update_task,
            parameters_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "ID of the task to update"},
                    "title": {"type": "string", "description": "Updated title"},
                    "description": {"type": "string", "description": "Updated description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Updated priority"},
                    "status": {"type": "string", "enum": ["pending", "completed", "cancelled"], "description": "Updated status"},
                    "due_at": {"type": "string", "description": "Updated ISO 8601 due date"},
                },
                "required": ["task_id"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="complete_task",
            description="Mark an existing task as completed.",
            friendly_name="Completing task",
            risk_level=RiskLevel.LOW_RISK_WRITE,
            func=execute_complete_task,
            parameters_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "ID of the task to complete"},
                },
                "required": ["task_id"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="delete_task",
            description="Delete an existing task. HIGH RISK: Requires explicit confirmation challenge token.",
            friendly_name="Deleting task",
            risk_level=RiskLevel.HIGH_RISK_WRITE,
            target_id_param="task_id",
            func=execute_delete_task,
            parameters_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "ID of the task to delete"},
                },
                "required": ["task_id"],
            },
        )
    )
