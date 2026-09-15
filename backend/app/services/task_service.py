from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select, func, desc, nullslast
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    """
    Task management service.
    Guarantees strict multi-user isolation on all CRUD operations.
    """

    @staticmethod
    async def create_task(db: AsyncSession, user_id: str, task_in: TaskCreate) -> Task:
        """Create a new task for the authenticated user."""
        task = Task(
            user_id=user_id,
            title=task_in.title,
            description=task_in.description,
            priority=task_in.priority,
            status="pending",
            due_at=task_in.due_at,
            timezone=task_in.timezone or "UTC",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_task(db: AsyncSession, user_id: str, task_id: str) -> Optional[Task]:
        """Get a single task by ID, scoped to user_id."""
        stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        user_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Task], int]:
        """List tasks for user with optional status/priority filtering and pagination."""
        base_query = select(Task).where(Task.user_id == user_id)
        count_query = select(func.count()).select_from(Task).where(Task.user_id == user_id)

        if status:
            base_query = base_query.where(Task.status == status)
            count_query = count_query.where(Task.status == status)
        if priority:
            base_query = base_query.where(Task.priority == priority)
            count_query = count_query.where(Task.priority == priority)

        total_res = await db.execute(count_query)
        total = total_res.scalar_one() or 0

        # Sort: pending first, then by due_at ascending (nulls last), then created_at desc
        stmt = (
            base_query.order_by(
                nullslast(Task.due_at.asc()),
                desc(Task.created_at),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await db.execute(stmt)
        items = list(res.scalars().all())
        return items, total

    @staticmethod
    async def update_task(
        db: AsyncSession, user_id: str, task_id: str, task_in: TaskUpdate
    ) -> Optional[Task]:
        """Update an existing task owned by the user."""
        task = await TaskService.get_task(db, user_id=user_id, task_id=task_id)
        if not task:
            return None

        update_data = task_in.model_dump(exclude_unset=True)
        if "status" in update_data:
            new_status = update_data["status"]
            if new_status == "completed" and task.status != "completed":
                task.completed_at = datetime.now(timezone.utc)
            elif new_status != "completed" and task.status == "completed":
                task.completed_at = None

        for field, val in update_data.items():
            setattr(task, field, val)

        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def complete_task(db: AsyncSession, user_id: str, task_id: str) -> Optional[Task]:
        """Mark a task as completed."""
        task = await TaskService.get_task(db, user_id=user_id, task_id=task_id)
        if not task:
            return None

        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def delete_task(db: AsyncSession, user_id: str, task_id: str) -> bool:
        """Delete a task owned by the user."""
        task = await TaskService.get_task(db, user_id=user_id, task_id=task_id)
        if not task:
            return False

        await db.delete(task)
        await db.commit()
        return True
