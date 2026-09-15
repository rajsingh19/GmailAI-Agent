"""
Proactive RAG Context Enricher (Milestone 8).
Retrieves relevant historical background notes/emails/tasks for detected meeting or email candidates.
Enforces strict user isolation and marks context as UNTRUSTED DATA with citations.
"""
import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


class ProactiveRAGEnricher:
    """
    Enriches high-priority proactive candidate alerts with relevant user knowledge
    via pgvector 768 semantic search.
    """

    def __init__(self, retrieval_service: Optional[RetrievalService] = None):
        self.retrieval_service = retrieval_service or RetrievalService()

    async def enrich_candidate(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        top_k: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """
        Queries user's personal knowledge base for context matching the query.
        Returns citations and formatted untrusted context blocks.
        """
        clean_query = query.strip()
        if not clean_query or len(clean_query) < 4:
            return None

        try:
            rag_res = await self.retrieval_service.search_knowledge(
                db=db,
                user_id=user_id,
                query=clean_query,
                top_k=min(2, top_k),
                similarity_threshold=0.60,
            )
            if rag_res.get("status") == "success" and rag_res.get("total_found", 0) > 0:
                return {
                    "citations": rag_res.get("citations", []),
                    "formatted_context": rag_res.get("formatted_context", ""),
                    "trusted": False,
                }
        except Exception as exc:
            logger.warning(f"ProactiveRAGEnricher error for user={user_id[:8]}: {exc}")

        return None
