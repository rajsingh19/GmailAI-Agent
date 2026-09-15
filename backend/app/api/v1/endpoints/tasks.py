from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse, TaskListResponse
from app.services.task_service import TaskService

router = APIRouter()


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new task for the authenticated user."""
    return await TaskService.create_task(db=db, user_id=current_user.id, task_in=task_in)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status: pending, completed, cancelled"),
    priority: Optional[str] = Query(None, description="Filter by priority: low, medium, high"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List tasks for the authenticated user with optional filtering."""
    items, total = await TaskService.list_tasks(
        db=db,
        user_id=current_user.id,
        status=status,
        priority=priority,
        limit=limit,
        offset=offset,
    )
    return TaskListResponse(items=items, total=total)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific task by ID."""
    task = await TaskService.get_task(db=db, user_id=current_user.id, task_id=task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_in: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a task owned by the authenticated user."""
    task = await TaskService.update_task(
        db=db, user_id=current_user.id, task_id=task_id, task_in=task_in
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )
    return task


@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a task as completed."""
    task = await TaskService.complete_task(db=db, user_id=current_user.id, task_id=task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a task owned by the authenticated user."""
    deleted = await TaskService.delete_task(db=db, user_id=current_user.id, task_id=task_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with ID '{task_id}' not found",
        )
    return None
