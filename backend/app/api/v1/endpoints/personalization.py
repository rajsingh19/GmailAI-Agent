"""
Personalization API Endpoints (Milestone 12).
Provides user configuration management, candidate preview for UI explainability,
and ephemeral session-level overrides.
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.personalization import (
    PersonalizationConfigResponse,
    PersonalizationConfigUpdate,
    PersonalizationPreviewRequest,
    PersonalizationPreviewResponse,
    PersonalizationSessionOverrideRequest,
    PersonalizationSessionOverrideResponse,
    PersonalizationLevel,
)
from app.services.personalization_service import PersonalizationService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config", response_model=PersonalizationConfigResponse)
async def get_personalization_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves the current user's personalization preferences.
    Guarantees strict user isolation based on authenticated session user_id.
    """
    config = await PersonalizationService.get_user_personalization_config(
        db=db, user_id=current_user.id
    )
    return PersonalizationConfigResponse(**config)


@router.patch("/config", response_model=PersonalizationConfigResponse)
async def update_personalization_config(
    config_in: PersonalizationConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Updates the current user's personalization preferences and immediately invalidates cache.
    """
    updated = await PersonalizationService.update_user_personalization_config(
        db=db, user_id=current_user.id, config_in=config_in
    )
    return PersonalizationConfigResponse(**updated)


@router.post("/preview", response_model=PersonalizationPreviewResponse)
async def preview_personalization_candidates(
    request: PersonalizationPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Simulates candidate relevance scoring and level/conflict filtering for a hypothetical user query.
    Returns sanitized candidate keys and selection status without leaking raw values or secrets.
    """
    clean_query = request.query.strip()[:500]
    if not clean_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query string cannot be empty.",
        )

    limit = min(max(request.limit, 1), 10)
    items = await PersonalizationService.preview_personalization(
        db=db, user_id=current_user.id, query=clean_query, limit=limit
    )

    return PersonalizationPreviewResponse(query=clean_query, items=items)


@router.post("/session-override", response_model=PersonalizationSessionOverrideResponse)
async def set_session_override(
    request: PersonalizationSessionOverrideRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Sets or clears an ephemeral session-level personalization override in Redis (1h TTL).
    Does NOT mutate persistent M11 memories or database preferences.
    """
    clean_session_id = request.session_id.strip()
    if not clean_session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id cannot be empty.",
        )

    # If disable_personalization is True -> enabled is False
    enabled = not request.disable_personalization
    await PersonalizationService.set_session_override(
        user_id=current_user.id, session_id=clean_session_id, enabled=enabled
    )

    msg = (
        f"Personalization disabled for session '{clean_session_id}'."
        if request.disable_personalization
        else f"Personalization resumed for session '{clean_session_id}'."
    )

    return PersonalizationSessionOverrideResponse(
        session_id=clean_session_id,
        personalization_disabled=request.disable_personalization,
        message=msg,
    )
