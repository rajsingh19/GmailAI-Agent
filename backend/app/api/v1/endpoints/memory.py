"""
Memory API Endpoints for Long-Term Personal Memory & Personalization (Milestone 11).
Enforces session authentication, verified user ownership, input bounds,
secret filtering, and zero cross-user existence leakage (404 on IDOR).
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.memory import (
    MemoryCreateRequest,
    MemoryUpdateRequest,
    MemoryResponse,
    MemoryListResponse,
    MemorySearchResponse,
    MemoryStatsResponse,
)
from app.services.memory_service import MemoryService, SecretDetectedError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    category: Optional[str] = Query(None, description="Filter by category"),
    active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists long-term memories for the authenticated user."""
    items, total = await MemoryService.list_memories(
        db=db,
        user_id=current_user.id,
        category=category,
        active=active,
        limit=limit,
        offset=offset,
    )
    return MemoryListResponse(
        status="success",
        total=total,
        count=len(items),
        items=[MemoryResponse.model_validate(m) for m in items],
    )


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    memory_in: MemoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates or updates a memory for the authenticated user with secret validation."""
    try:
        memory = await MemoryService.create_or_upsert_memory(
            db=db,
            user_id=current_user.id,
            memory_in=memory_in,
        )
        return MemoryResponse.model_validate(memory)
    except SecretDetectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Error creating memory: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save memory.",
        )


@router.get("/search", response_model=MemorySearchResponse)
async def search_memories(
    query: str = Query(..., min_length=1, max_length=200, description="Search term"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Searches memories with deterministic relevance scoring."""
    results = await MemoryService.search_memories(
        db=db,
        user_id=current_user.id,
        query=query,
        category=category,
        limit=limit,
    )
    return MemorySearchResponse(
        status="success",
        total_found=len(results),
        results=[MemoryResponse.model_validate(m) for m in results],
    )


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves aggregated memory statistics for the dashboard."""
    stats = await MemoryService.get_memory_stats(db=db, user_id=current_user.id)
    return MemoryStatsResponse(**stats)


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves a specific memory by ID. Enforces strict user isolation (404 on IDOR)."""
    memory = await MemoryService.get_memory(db=db, user_id=current_user.id, memory_id=memory_id)
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found.",
        )
    return MemoryResponse.model_validate(memory)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    update_in: MemoryUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates an existing memory. Enforces user isolation and secret scanning."""
    try:
        memory = await MemoryService.update_memory(
            db=db,
            user_id=current_user.id,
            memory_id=memory_id,
            update_in=update_in,
        )
        if not memory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Memory '{memory_id}' not found.",
            )
        return MemoryResponse.model_validate(memory)
    except SecretDetectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post("/{memory_id}/deactivate", response_model=MemoryResponse)
async def deactivate_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deactivates a memory without permanent deletion."""
    memory = await MemoryService.deactivate_memory(
        db=db,
        user_id=current_user.id,
        memory_id=memory_id,
    )
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found.",
        )
    return MemoryResponse.model_validate(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently deletes a memory with exact user ownership check."""
    deleted = await MemoryService.delete_memory(
        db=db,
        user_id=current_user.id,
        memory_id=memory_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory '{memory_id}' not found.",
        )
    return None
