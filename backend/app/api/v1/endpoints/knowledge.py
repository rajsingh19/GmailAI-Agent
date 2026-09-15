"""
Personal Knowledge & RAG API Endpoints (Milestone 7).
Enforces session-based authentication, user isolation, and bounded parameter validation.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeStatusResponse,
    KnowledgeReindexResponse,
    KnowledgeResultItem,
    KnowledgeCitation,
)
from app.services.retrieval_service import RetrievalService
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status", response_model=KnowledgeStatusResponse)
async def get_knowledge_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns knowledge indexing statistics (document counts, chunk counts, last indexed time)
    for the authenticated user.
    """
    service = RetrievalService()
    status_data = await service.get_knowledge_status(db=db, user_id=current_user.id)
    return KnowledgeStatusResponse(**status_data)


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Executes semantic vector search across the authenticated user's indexed knowledge base.
    Returns ranked excerpts with similarity scores and verified citations.
    """
    service = RetrievalService()
    search_data = await service.search_knowledge(
        db=db,
        user_id=current_user.id,
        query=request.query,
        source_type=request.source_type,
        top_k=request.top_k,
        similarity_threshold=request.similarity_threshold,
    )
    return KnowledgeSearchResponse(
        status=search_data["status"],
        total_found=search_data["total_found"],
        results=[KnowledgeResultItem(**r) for r in search_data["results"]],
        citations=[KnowledgeCitation(**c) for c in search_data["citations"]],
    )


@router.post("/reindex", response_model=KnowledgeReindexResponse)
async def reindex_knowledge(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers bounded, idempotent reindexing across all authorized sources (Gmail, Calendar, Tasks, Reminders)
    for the authenticated user.
    """
    service = IngestionService()
    reindex_data = await service.reindex_all_sources(db=db, user=current_user)
    return KnowledgeReindexResponse(**reindex_data)
