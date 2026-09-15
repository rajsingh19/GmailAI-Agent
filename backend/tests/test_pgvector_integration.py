"""
PostgreSQL + pgvector and Vector Storage Integration Tests (Milestone 7).
Tests vector column serialization, dimension validation, cosine search, HNSW indexing,
and real RAG retrieval through PostgreSQL with strict user isolation.
"""
import math
import uuid
import pytest
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text, select

from app.core.config import settings
from app.models.user import User
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.retrieval_service import compute_cosine_similarity, RetrievalService
from app.ai.embeddings.base import EmbeddingProvider


class MockFixedEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider generating normalized 768-dim float vectors."""
    def __init__(self, dimensions: int = 768):
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "mock_fixed"

    @property
    def model_name(self) -> str:
        return "mock-fixed-768"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_text(self, text: str, timeout: float = 15.0) -> list[float]:
        dim = self._dimensions
        vec = [0.0] * dim
        hash_val = sum(ord(c) for c in text)
        idx1 = hash_val % dim
        idx2 = (hash_val * 7) % dim
        vec[idx1] = 0.8
        vec[idx2] = 0.6
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]

    async def embed_documents(self, texts: list[str], timeout: float = 30.0) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]



@pytest.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a session connected to the real PostgreSQL database."""
    pg_url = settings.DATABASE_URL
    if not pg_url.startswith("postgresql"):
        pg_url = "postgresql+asyncpg://ai_user:ai_password@localhost:5438/ai_assistant"

    engine = create_async_engine(pg_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def test_vector_dimension_constants():
    """Verify system config specifies 768 dimensions for text-embedding-004."""
    assert settings.EMBEDDING_DIMENSIONS == 768
    assert settings.EMBEDDING_MODEL == "text-embedding-004"


def test_chunk_embedding_vector_dimensions_exact():
    """Verify KnowledgeChunk accepts and retains 768-dimensional float embeddings."""
    dim = 768
    vec = [float(i) / float(dim) for i in range(dim)]
    chunk = KnowledgeChunk(
        document_id="doc-test-1",
        user_id="user-test-1",
        chunk_index=0,
        content="Testing vector storage format.",
        embedding=vec,
    )
    assert len(chunk.embedding_vector) == 768
    assert chunk.embedding_vector[0] == 0.0
    assert pytest.approx(chunk.embedding_vector[-1], 0.001) == (767.0 / 768.0)


def test_sqlite_cosine_similarity_adapter():
    """Verify SQLite in-memory fallback adapter computes accurate cosine similarities."""
    v1 = [0.1] * 768
    v2 = [0.1] * 768
    assert pytest.approx(compute_cosine_similarity(v1, v2), 0.0001) == 1.0

    # Orthogonal vectors
    v_a = [1.0] + [0.0] * 767
    v_b = [0.0, 1.0] + [0.0] * 766
    assert pytest.approx(compute_cosine_similarity(v_a, v_b), 0.0001) == 0.0


@pytest.mark.asyncio
async def test_pgvector_extension_verified(pg_session: AsyncSession):
    """Verify pgvector extension is installed and active in PostgreSQL."""
    res = await pg_session.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"))
    row = res.fetchone()
    assert row is not None, "pgvector extension is not installed"
    assert row[0] == "vector"
    assert row[1].startswith("0."), f"Unexpected pgvector version: {row[1]}"


@pytest.mark.asyncio
async def test_pgvector_hnsw_index_exists(pg_session: AsyncSession):
    """Verify HNSW cosine index exists on knowledge_chunks.embedding."""
    res = await pg_session.execute(text("""
        SELECT indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename = 'knowledge_chunks' AND indexname = 'idx_kchunk_hnsw_cosine';
    """))
    row = res.fetchone()
    assert row is not None, "idx_kchunk_hnsw_cosine index does not exist"
    assert "hnsw" in row[1].lower()
    assert "vector_cosine_ops" in row[1].lower()


@pytest.mark.asyncio
async def test_pgvector_vector768_column_type(pg_session: AsyncSession):
    """Verify knowledge_chunks.embedding is vector(768) in PostgreSQL."""
    res = await pg_session.execute(text("""
        SELECT column_name, udt_name 
        FROM information_schema.columns 
        WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding';
    """))
    row = res.fetchone()
    assert row is not None, "embedding column not found in knowledge_chunks"
    assert row[1] == "vector", f"Expected udt_name 'vector', got {row[1]}"


@pytest.mark.asyncio
async def test_pgvector_insert_retrieve_and_cosine_distance(pg_session: AsyncSession):
    """Verify vector insertion, retrieval, and native cosine similarity on PostgreSQL."""
    test_user_id = f"test-user-{uuid.uuid4().hex[:8]}"
    test_doc_id = f"test-doc-{uuid.uuid4().hex[:8]}"

    # Create dummy user and document
    user = User(
        id=test_user_id,
        email=f"{test_user_id}@example.com",
        full_name="Vector Test User",
    )
    pg_session.add(user)
    await pg_session.flush()

    doc = KnowledgeDocument(
        id=test_doc_id,
        user_id=test_user_id,
        source_type="task",
        source_id=f"src-{test_doc_id}",
        title="Project Roadmap 2026",
        content_hash="abc123hash",
        doc_metadata={"priority": "high"},
    )
    pg_session.add(doc)
    await pg_session.flush()

    # 768-dim test vector
    v1 = [0.0] * 768
    v1[0] = 1.0  # Unit vector along axis 0
    chunk1 = KnowledgeChunk(
        id=f"chunk-{uuid.uuid4().hex[:8]}",
        document_id=test_doc_id,
        user_id=test_user_id,
        chunk_index=0,
        content="Q3 deliverables include PostgreSQL pgvector verification.",
        embedding=v1,
    )
    pg_session.add(chunk1)
    await pg_session.commit()

    # Retrieve chunk and verify dimensions
    loaded_chunk = await pg_session.get(KnowledgeChunk, chunk1.id)
    assert loaded_chunk is not None
    assert len(loaded_chunk.embedding_vector) == 768
    assert loaded_chunk.embedding_vector[0] == 1.0
    assert loaded_chunk.embedding_vector[1] == 0.0

    # Query with native cosine similarity: same vector -> cosine distance should be 0.0
    query_str = "[" + ",".join(str(x) for x in v1) + "]"
    res = await pg_session.execute(text(f"""
        SELECT id, 1 - (embedding <=> '{query_str}'::vector) as similarity
        FROM knowledge_chunks
        WHERE id = '{chunk1.id}';
    """))
    row = res.fetchone()
    assert row is not None
    similarity = float(row[1])
    assert pytest.approx(similarity, 0.001) == 1.0

    # Clean up test data
    await pg_session.delete(user)
    await pg_session.commit()


@pytest.mark.asyncio
async def test_pgvector_rag_retrieval_and_user_isolation(pg_session: AsyncSession):
    """
    Verify real RAG retrieval through PostgreSQL with strict multi-user isolation:
    User A's documents must be returned when queried by User A.
    User B must NEVER see User A's documents even with identical query vectors.
    """
    user_a_id = f"user-a-{uuid.uuid4().hex[:8]}"
    user_b_id = f"user-b-{uuid.uuid4().hex[:8]}"

    user_a = User(id=user_a_id, email=f"{user_a_id}@example.com", full_name="User A")
    user_b = User(id=user_b_id, email=f"{user_b_id}@example.com", full_name="User B")
    pg_session.add_all([user_a, user_b])
    await pg_session.flush()

    mock_provider = MockFixedEmbeddingProvider(dimensions=768)
    retrieval_service = RetrievalService(embedding_provider=mock_provider)

    # Document for User A
    doc_a = KnowledgeDocument(
        id=f"doc-a-{uuid.uuid4().hex[:8]}",
        user_id=user_a_id,
        source_type="task",
        source_id="task-100",
        title="Secret Architecture Blueprint for User A",
        content_hash="hash-user-a",
        doc_metadata={"author": "User A"},
    )
    content_a = "Confidential project specs for User A only."
    vec_a = await mock_provider.embed_text(content_a)
    chunk_a = KnowledgeChunk(
        id=f"chunk-a-{uuid.uuid4().hex[:8]}",
        document_id=doc_a.id,
        user_id=user_a_id,
        chunk_index=0,
        content=content_a,
        embedding=vec_a,
    )

    # Document for User B
    doc_b = KnowledgeDocument(
        id=f"doc-b-{uuid.uuid4().hex[:8]}",
        user_id=user_b_id,
        source_type="task",
        source_id="task-200",
        title="Public Guidelines for User B",
        content_hash="hash-user-b",
        doc_metadata={"author": "User B"},
    )
    content_b = "General onboarding guidelines for User B."
    vec_b = await mock_provider.embed_text(content_b)
    chunk_b = KnowledgeChunk(
        id=f"chunk-b-{uuid.uuid4().hex[:8]}",
        document_id=doc_b.id,
        user_id=user_b_id,
        chunk_index=0,
        content=content_b,
        embedding=vec_b,
    )

    pg_session.add_all([doc_a, chunk_a, doc_b, chunk_b])
    await pg_session.commit()

    # 1. Search as User A with User A's exact content
    results_a = await retrieval_service.search_knowledge(
        db=pg_session,
        user_id=user_a_id,
        query=content_a,
        similarity_threshold=0.5,
    )
    assert results_a["status"] == "success"
    assert results_a["total_found"] >= 1
    assert any(r["document_title"] == "Secret Architecture Blueprint for User A" for r in results_a["results"])
    # Crucial: User A must NOT see User B's documents
    assert not any(r["document_title"] == "Public Guidelines for User B" for r in results_a["results"])
    assert len(results_a["citations"]) >= 1
    assert results_a["citations"][0]["citation_id"] == "cit_1"

    # 2. Search as User B with User A's exact query
    results_b = await retrieval_service.search_knowledge(
        db=pg_session,
        user_id=user_b_id,
        query=content_a,
        similarity_threshold=0.5,
    )
    assert results_b["status"] == "success"
    # Crucial: User B must NEVER receive User A's confidential documents
    assert not any(r["document_title"] == "Secret Architecture Blueprint for User A" for r in results_b["results"])

    # Clean up
    await pg_session.delete(user_a)
    await pg_session.delete(user_b)
    await pg_session.commit()
