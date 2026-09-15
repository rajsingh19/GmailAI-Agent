"""
Retrieval Service for Personal Knowledge RAG (Milestone 7).
Executes user-scoped semantic vector similarity searches, threshold filtering, and backend-controlled citation generation.
"""
import math
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk

logger = logging.getLogger(__name__)


def compute_cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Computes cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class RetrievalService:
    """
    Manages semantic search across a user's isolated knowledge base.
    Guarantees user-level isolation and generates untrusted delimited context blocks with citations.
    """

    def __init__(self, embedding_provider: Optional[Any] = None):
        if embedding_provider is not None:
            self.embedder = embedding_provider
        else:
            from app.ai.embeddings.gemini_embeddings import GeminiEmbeddingProvider
            self.embedder = GeminiEmbeddingProvider()


    async def search_knowledge(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        source_type: Optional[str] = None,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Executes semantic vector search strictly scoped to the authenticated user.
        
        Args:
            db: Database session
            user_id: Authenticated user ID (strictly enforced)
            query: Natural language query string
            source_type: Optional source filter ('gmail', 'calendar', 'task', 'reminder')
            top_k: Max results to return (default 5, max 10)
            similarity_threshold: Min similarity score (default 0.65)
        
        Returns:
            Dict with 'results', 'citations', 'formatted_context', 'trusted': False
        """
        clean_query = query.strip()
        if not clean_query:
            return {
                "status": "success",
                "source": "personal_knowledge",
                "trusted": False,
                "total_found": 0,
                "results": [],
                "citations": [],
                "formatted_context": "No search query provided.",
            }

        k = min(10, max(1, top_k or settings.RAG_TOP_K))
        threshold = similarity_threshold if similarity_threshold is not None else settings.RAG_SIMILARITY_THRESHOLD

        # 1. Generate query embedding vector
        query_vector = await self.embedder.embed_text(clean_query)

        # 2. Query active chunks belonging strictly to the user
        conditions = [
            KnowledgeChunk.user_id == user_id,
            KnowledgeDocument.status == "active",
        ]

        if source_type:
            conditions.append(KnowledgeDocument.source_type == source_type.lower().strip())

        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(and_(*conditions))
        )

        db_results = (await db.execute(stmt)).all()

        # 3. Calculate cosine similarity and filter by threshold
        scored_items = []
        for chunk, doc in db_results:
            sim = compute_cosine_similarity(query_vector, chunk.embedding)
            if sim >= threshold:
                scored_items.append((sim, chunk, doc))

        # 4. Sort descending by similarity and take top_k
        scored_items.sort(key=lambda x: x[0], reverse=True)
        top_items = scored_items[:k]

        # 5. Build structured results and backend-controlled citations
        results: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []
        context_blocks: List[str] = []

        for idx, (score, chunk, doc) in enumerate(top_items):
            citation_id = f"cit_{idx + 1}"
            rounded_score = round(score, 3)

            result_item = {
                "citation_id": citation_id,
                "source_type": doc.source_type,
                "source_id": doc.source_id,
                "title": doc.title,
                "document_title": doc.title,
                "snippet": chunk.content,
                "similarity_score": rounded_score,
                "similarity": rounded_score,
                "timestamp": doc.doc_metadata.get("timestamp") or doc.doc_metadata.get("start") or doc.created_at.isoformat(),
                "metadata": doc.doc_metadata,
            }
            results.append(result_item)

            citations.append({
                "citation_id": citation_id,
                "source_type": doc.source_type,
                "source_id": doc.source_id,
                "title": doc.title,
                "snippet": chunk.content[:200],
                "similarity_score": rounded_score,
            })

            context_blocks.append(
                f"=== BEGIN UNTRUSTED RETRIEVED CONTEXT (Citation ID: {citation_id} | Source: {doc.source_type.capitalize()} | Title: {doc.title} | Score: {rounded_score}) ===\n"
                f"{chunk.content}\n"
                f"=== END UNTRUSTED RETRIEVED CONTEXT ==="
            )

        formatted_context = "\n\n".join(context_blocks) if context_blocks else "No relevant personal knowledge found matching the query."

        return {
            "status": "success",
            "source": "personal_knowledge",
            "trusted": False,
            "total_found": len(results),
            "results": results,
            "citations": citations,
            "formatted_context": formatted_context,
        }

    async def get_knowledge_status(self, db: AsyncSession, user_id: str) -> Dict[str, Any]:
        """Returns knowledge indexing statistics for the authenticated user."""
        # 1. Total documents and breakdown by source
        doc_stmt = (
            select(
                KnowledgeDocument.source_type,
                func.count(KnowledgeDocument.id).label("doc_count"),
                func.max(KnowledgeDocument.indexed_at).label("last_indexed"),
            )
            .where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.status == "active",
            )
            .group_by(KnowledgeDocument.source_type)
        )
        doc_rows = (await db.execute(doc_stmt)).all()

        # 2. Total chunks
        chunk_stmt = (
            select(func.count(KnowledgeChunk.id))
            .where(KnowledgeChunk.user_id == user_id)
        )
        total_chunks = (await db.execute(chunk_stmt)).scalar_one() or 0

        sources_summary: Dict[str, Any] = {}
        total_docs = 0
        latest_indexed: Optional[str] = None

        for row in doc_rows:
            source_type, count, last_ts = row
            total_docs += count
            ts_iso = last_ts.isoformat() if last_ts else None
            sources_summary[source_type] = {
                "document_count": count,
                "last_indexed": ts_iso,
            }
            if ts_iso and (latest_indexed is None or ts_iso > latest_indexed):
                latest_indexed = ts_iso

        return {
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "last_indexed": latest_indexed,
            "sources": sources_summary,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
        }
