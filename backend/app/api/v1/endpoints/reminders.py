from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.reminder import (
    ReminderCreate,
    ReminderUpdate,
    ReminderSnooze,
    ReminderResponse,
    ReminderListResponse,
)
from app.services.reminder_service import ReminderService

router = APIRouter()


@router.post("", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    reminder_in: ReminderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new reminder for the authenticated user."""
    try:
        return await ReminderService.create_reminder(
            db=db, user_id=current_user.id, reminder_in=reminder_in
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("", response_model=ReminderListResponse)
async def list_reminders(
    status: Optional[str] = Query(None, description="Filter by status"),
    task_id: Optional[str] = Query(None, description="Filter by task ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List reminders for the authenticated user."""
    items, total = await ReminderService.list_reminders(
        db=db,
        user_id=current_user.id,
        status=status,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    return ReminderListResponse(items=items, total=total)


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific reminder by ID."""
    reminder = await ReminderService.get_reminder(
        db=db, user_id=current_user.id, reminder_id=reminder_id
    )
    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder with ID '{reminder_id}' not found",
        )
    return reminder


@router.patch("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    reminder_id: str,
    reminder_in: ReminderUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a reminder owned by the authenticated user."""
    try:
        reminder = await ReminderService.update_reminder(
            db=db, user_id=current_user.id, reminder_id=reminder_id, reminder_in=reminder_in
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder with ID '{reminder_id}' not found",
        )
    return reminder


@router.post("/{reminder_id}/snooze", response_model=ReminderResponse)
async def snooze_reminder(
    reminder_id: str,
    snooze_in: ReminderSnooze,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Snooze a reminder to a later time."""
    try:
        reminder = await ReminderService.snooze_reminder(
            db=db, user_id=current_user.id, reminder_id=reminder_id, snooze_in=snooze_in
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder with ID '{reminder_id}' not found",
        )
    return reminder


@router.post("/{reminder_id}/cancel", response_model=ReminderResponse)
async def cancel_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a reminder."""
    reminder = await ReminderService.cancel_reminder(
        db=db, user_id=current_user.id, reminder_id=reminder_id
    )
    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder with ID '{reminder_id}' not found",
        )
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a reminder owned by the authenticated user."""
    deleted = await ReminderService.delete_reminder(
        db=db, user_id=current_user.id, reminder_id=reminder_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder with ID '{reminder_id}' not found",
        )
    return None
