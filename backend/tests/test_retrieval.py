"""
Unit and integration tests for RetrievalService and Semantic Vector Search (Milestone 7).
Validates cosine similarity calculation, top_k ranking, threshold filtering, metadata filtering,
backend citation formatting, inactive document exclusion, and STRICT multi-user isolation.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.services.retrieval_service import RetrievalService, compute_cosine_similarity
from app.ai.embeddings.base import EmbeddingProvider


class DirectionalMockEmbedder(EmbeddingProvider):
    """
    Mock embedder that returns unit vectors along specific axes to test exact cosine similarities:
    - 'budget' -> [1.0, 0.0, ...]
    - 'finance' -> [0.9, 0.1, ...]
    - 'meeting' -> [0.0, 1.0, ...]
    - 'unrelated' -> [-1.0, 0.0, ...]
    """

    def __init__(self, dimension: int = 768):
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "directional-mock"

    @property
    def dimensions(self) -> int:
        return self._dimension

    async def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        t_lower = text.lower()
        if "budget" in t_lower:
            vec[0] = 1.0
        elif "finance" in t_lower:
            vec[0] = 0.85
            vec[1] = 0.15
        elif "meeting" in t_lower:
            vec[1] = 1.0
        elif "unrelated" in t_lower:
            vec[2] = 1.0
        else:
            vec[0] = 0.5
            vec[1] = 0.5
        return vec

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]


@pytest.fixture
def directional_embedder():
    return DirectionalMockEmbedder(dimension=768)


@pytest.fixture
def retrieval_service(directional_embedder):
    return RetrievalService(embedding_provider=directional_embedder)


@pytest.fixture
async def user_a(test_db: AsyncSession) -> User:
    u = User(email="user_a@example.com", full_name="User Alpha", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.fixture
async def user_b(test_db: AsyncSession) -> User:
    u = User(email="user_b@example.com", full_name="User Beta", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


def test_cosine_similarity_math():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    v4 = [-1.0, 0.0, 0.0]

    assert pytest.approx(compute_cosine_similarity(v1, v2), 0.001) == 1.0
    assert pytest.approx(compute_cosine_similarity(v1, v3), 0.001) == 0.0
    assert pytest.approx(compute_cosine_similarity(v1, v4), 0.001) == -1.0
    assert compute_cosine_similarity([], v1) == 0.0
    assert compute_cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


@pytest.mark.asyncio
async def test_search_knowledge_ranking_and_top_k(test_db: AsyncSession, user_a: User, retrieval_service):
    # Ingest 3 documents for user_a
    doc1 = KnowledgeDocument(
        user_id=user_a.id,
        source_type="gmail",
        source_id="msg-1",
        title="Q3 Budget Final Report",
        content_hash="hash1",
        status="active",
    )
    doc2 = KnowledgeDocument(
        user_id=user_a.id,
        source_type="tasks",
        source_id="task-1",
        title="Finance Sync Task",
        content_hash="hash2",
        status="active",
    )
    doc3 = KnowledgeDocument(
        user_id=user_a.id,
        source_type="calendar",
        source_id="cal-1",
        title="General Team Meeting",
        content_hash="hash3",
        status="active",
    )
    test_db.add_all([doc1, doc2, doc3])
    await test_db.flush()

    chunk1 = KnowledgeChunk(
        document_id=doc1.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Q3 Budget numbers and final balance.",
        embedding=[1.0] + [0.0] * 767,
    )
    chunk2 = KnowledgeChunk(
        document_id=doc2.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Finance sync and team expenses.",
        embedding=[0.85, 0.15] + [0.0] * 766,
    )
    chunk3 = KnowledgeChunk(
        document_id=doc3.id,
        user_id=user_a.id,
        chunk_index=0,
        content="General all hands meeting agenda.",
        embedding=[0.0, 1.0] + [0.0] * 766,
    )
    test_db.add_all([chunk1, chunk2, chunk3])
    await test_db.commit()

    # Query for 'budget'
    search_res = await retrieval_service.search_knowledge(
        db=test_db,
        user_id=user_a.id,
        query="budget",
        top_k=2,
        similarity_threshold=0.5,
    )

    assert search_res["status"] == "success"
    assert search_res["trusted"] is False
    assert len(search_res["results"]) == 2
    # doc1 has highest similarity (1.0), followed by doc2 (~0.85)
    assert search_res["results"][0]["document_title"] == "Q3 Budget Final Report"
    assert pytest.approx(search_res["results"][0]["similarity"], 0.01) == 1.0
    assert search_res["results"][1]["document_title"] == "Finance Sync Task"


@pytest.mark.asyncio
async def test_search_knowledge_threshold_filtering(test_db: AsyncSession, user_a: User, retrieval_service):
    doc = KnowledgeDocument(
        user_id=user_a.id,
        source_type="calendar",
        source_id="cal-meeting",
        title="Weekly Sync",
        content_hash="hash_sync",
        status="active",
    )
    test_db.add(doc)
    await test_db.flush()

    chunk = KnowledgeChunk(
        document_id=doc.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Meeting notes",
        embedding=[0.0, 1.0] + [0.0] * 766,  # Orthogonal to budget
    )
    test_db.add(chunk)
    await test_db.commit()

    # Search with high threshold (0.7) for budget should return 0 results
    search_res = await retrieval_service.search_knowledge(
        db=test_db,
        user_id=user_a.id,
        query="budget",
        similarity_threshold=0.7,
    )
    assert len(search_res["results"]) == 0
    assert len(search_res["citations"]) == 0


@pytest.mark.asyncio
async def test_strict_multi_user_isolation(test_db: AsyncSession, user_a: User, user_b: User, retrieval_service):
    """
    CRITICAL: User A must never see User B's knowledge, even if User B's chunk
    is a 100% exact vector match for User A's query.
    """
    # User B has secret document with 100% match for 'budget'
    doc_b = KnowledgeDocument(
        user_id=user_b.id,
        source_type="gmail",
        source_id="msg-secret-b",
        title="User B Secret Budget Plan",
        content_hash="hash_b",
        status="active",
    )
    test_db.add(doc_b)
    await test_db.flush()

    chunk_b = KnowledgeChunk(
        document_id=doc_b.id,
        user_id=user_b.id,
        chunk_index=0,
        content="Secret revenue numbers of User B: $10,000,000.",
        embedding=[1.0] + [0.0] * 767,
    )
    test_db.add(chunk_b)
    await test_db.commit()

    # User A searches for 'budget'
    search_res = await retrieval_service.search_knowledge(
        db=test_db,
        user_id=user_a.id,
        query="budget",
        similarity_threshold=0.1,
    )

    # Must be completely empty for User A
    assert len(search_res["results"]) == 0
    assert "Secret revenue" not in search_res["formatted_context"]


@pytest.mark.asyncio
async def test_source_type_filter(test_db: AsyncSession, user_a: User, retrieval_service):
    doc_gmail = KnowledgeDocument(
        user_id=user_a.id,
        source_type="gmail",
        source_id="g-1",
        title="Email from CFO",
        content_hash="hg",
        status="active",
    )
    doc_task = KnowledgeDocument(
        user_id=user_a.id,
        source_type="tasks",
        source_id="t-1",
        title="Task: Submit Budget",
        content_hash="ht",
        status="active",
    )
    test_db.add_all([doc_gmail, doc_task])
    await test_db.flush()

    chunk_gmail = KnowledgeChunk(
        document_id=doc_gmail.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Budget approval details in email.",
        embedding=[1.0] + [0.0] * 767,
    )
    chunk_task = KnowledgeChunk(
        document_id=doc_task.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Budget task submission details.",
        embedding=[1.0] + [0.0] * 767,
    )
    test_db.add_all([chunk_gmail, chunk_task])
    await test_db.commit()

    # Search with source_type='tasks'
    search_res = await retrieval_service.search_knowledge(
        db=test_db,
        user_id=user_a.id,
        query="budget",
        source_type="tasks",
        similarity_threshold=0.5,
    )

    assert len(search_res["results"]) == 1
    assert search_res["results"][0]["source_type"] == "tasks"
    assert search_res["results"][0]["document_title"] == "Task: Submit Budget"


@pytest.mark.asyncio
async def test_inactive_and_deleted_documents_excluded(test_db: AsyncSession, user_a: User, retrieval_service):
    doc_deleted = KnowledgeDocument(
        user_id=user_a.id,
        source_type="tasks",
        source_id="t-del",
        title="Deleted Old Budget",
        content_hash="hdel",
        status="deleted",
    )
    doc_archived = KnowledgeDocument(
        user_id=user_a.id,
        source_type="tasks",
        source_id="t-arch",
        title="Archived Old Budget",
        content_hash="harch",
        status="archived",
    )
    test_db.add_all([doc_deleted, doc_archived])
    await test_db.flush()

    chunk_del = KnowledgeChunk(
        document_id=doc_deleted.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Deleted budget content.",
        embedding=[1.0] + [0.0] * 767,
    )
    chunk_arch = KnowledgeChunk(
        document_id=doc_archived.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Archived budget content.",
        embedding=[1.0] + [0.0] * 767,
    )
    test_db.add_all([chunk_del, chunk_arch])
    await test_db.commit()

    search_res = await retrieval_service.search_knowledge(
        db=test_db,
        user_id=user_a.id,
        query="budget",
        similarity_threshold=0.1,
    )
    assert len(search_res["results"]) == 0


@pytest.mark.asyncio
async def test_backend_citation_formatting(test_db: AsyncSession, user_a: User, retrieval_service):
    doc = KnowledgeDocument(
        user_id=user_a.id,
        source_type="gmail",
        source_id="msg-deploy",
        title="Deployment Roadmap",
        content_hash="h_road",
        status="active",
    )
    test_db.add(doc)
    await test_db.flush()

    chunk = KnowledgeChunk(
        document_id=doc.id,
        user_id=user_a.id,
        chunk_index=0,
        content="Milestone 7 RAG is deploying on Tuesday.",
        embedding=[1.0] + [0.0] * 767,
    )
    test_db.add(chunk)
    await test_db.commit()

    search_res = await retrieval_service.search_knowledge(
        db=test_db,
        user_id=user_a.id,
        query="budget",
        similarity_threshold=0.5,
    )

    assert len(search_res["citations"]) == 1
    cit = search_res["citations"][0]
    assert cit["citation_id"] == "cit_1"
    assert cit["source_type"] == "gmail"
    assert cit["title"] == "Deployment Roadmap"
    assert "Milestone 7" in cit["snippet"]

    # Verify untrusted delimiters in formatted_context
    assert "UNTRUSTED RETRIEVED CONTEXT" in search_res["formatted_context"]
    assert "Citation ID: cit_1" in search_res["formatted_context"]


@pytest.mark.asyncio
async def test_empty_query_returns_safe_empty_response(test_db: AsyncSession, user_a: User, retrieval_service):
    search_res = await retrieval_service.search_knowledge(
        db=test_db,
        user_id=user_a.id,
        query="   ",
    )
    assert search_res["total_found"] == 0
    assert search_res["trusted"] is False
    assert search_res["results"] == []
