"""
Tests for Knowledge REST API Endpoints (Milestone 7).
Validates:
- Authentication enforcement (HTTP 401 on missing session cookie)
- GET /api/v1/knowledge/status
- POST /api/v1/knowledge/search
- POST /api/v1/knowledge/reindex
- Input validation on search query and filters
- Multi-user data isolation via API requests
"""
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk


async def create_user(db: AsyncSession, email: str = "api_rag_user@example.com") -> User:
    u = User(email=email, full_name="API RAG Tester", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def authenticate_client(client: AsyncClient, user: User):
    token = SecurityManager.create_session_token(user_id=user.id)
    client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_knowledge_endpoints_require_auth(async_client: AsyncClient):
    """All /api/v1/knowledge/* endpoints must require authentication."""
    res_status = await async_client.get("/api/v1/knowledge/status")
    assert res_status.status_code == 401

    res_search = await async_client.post("/api/v1/knowledge/search", json={"query": "test"})
    assert res_search.status_code == 401

    res_reindex = await async_client.post("/api/v1/knowledge/reindex")
    assert res_reindex.status_code == 401


@pytest.mark.asyncio
async def test_get_knowledge_status_authenticated(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_user(test_db, "status_user@example.com")
    authenticate_client(async_client, user)

    # Ingest a sample doc
    doc = KnowledgeDocument(
        user_id=user.id,
        source_type="tasks",
        source_id="t-1",
        title="Sample Task",
        content_hash="h123",
        status="active",
    )
    test_db.add(doc)
    await test_db.flush()

    chunk = KnowledgeChunk(
        document_id=doc.id,
        user_id=user.id,
        chunk_index=0,
        content="Sample chunk content",
        embedding=[0.1] * 768,
    )
    test_db.add(chunk)
    await test_db.commit()

    res = await async_client.get("/api/v1/knowledge/status")
    assert res.status_code == 200
    data = res.json()
    assert data["total_documents"] >= 1
    assert data["total_chunks"] >= 1
    assert "tasks" in data["sources"]
    assert data["embedding_model"] == settings.EMBEDDING_MODEL
    assert data["embedding_dimensions"] == settings.EMBEDDING_DIMENSIONS


@pytest.mark.asyncio
async def test_search_knowledge_authenticated(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_user(test_db, "search_api_user@example.com")
    authenticate_client(async_client, user)

    mock_search_res = {
        "status": "success",
        "source": "personal_knowledge",
        "trusted": False,
        "total_found": 1,
        "results": [
            {
                "citation_id": "cit_1",
                "source_type": "gmail",
                "source_id": "msg-api-1",
                "title": "Roadmap Q4",
                "snippet": "Q4 plan is approved.",
                "similarity_score": 0.92,
                "similarity": 0.92,
                "timestamp": "2026-09-15T12:00:00Z",
                "metadata": {},
            }
        ],
        "citations": [
            {
                "citation_id": "cit_1",
                "source_type": "gmail",
                "source_id": "msg-api-1",
                "title": "Roadmap Q4",
                "snippet": "Q4 plan is approved.",
                "similarity_score": 0.92,
            }
        ],
        "formatted_context": "=== BEGIN UNTRUSTED RETRIEVED CONTEXT ===\nQ4 plan is approved.\n=== END UNTRUSTED RETRIEVED CONTEXT ===",
    }

    with patch("app.api.v1.endpoints.knowledge.RetrievalService") as mock_ret_cls:
        mock_ret = MagicMock()
        mock_ret.search_knowledge = AsyncMock(return_value=mock_search_res)
        mock_ret_cls.return_value = mock_ret

        res = await async_client.post(
            "/api/v1/knowledge/search",
            json={"query": "roadmap", "top_k": 3, "similarity_threshold": 0.6},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["total_found"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Roadmap Q4"
        assert len(data["citations"]) == 1


@pytest.mark.asyncio
async def test_search_knowledge_validation_errors(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_user(test_db, "validation_user@example.com")
    authenticate_client(async_client, user)

    # Empty query string
    res = await async_client.post("/api/v1/knowledge/search", json={"query": ""})
    assert res.status_code == 422

    # Negative top_k
    res2 = await async_client.post("/api/v1/knowledge/search", json={"query": "valid", "top_k": -1})
    assert res2.status_code == 422


@pytest.mark.asyncio
async def test_reindex_knowledge_authenticated(async_client: AsyncClient, test_db: AsyncSession):
    user = await create_user(test_db, "reindex_api_user@example.com")
    authenticate_client(async_client, user)

    mock_reindex_res = {
        "status": "completed",
        "documents_processed": 5,
        "documents_indexed": 3,
        "documents_skipped": 2,
        "chunks_created": 6,
        "duration_ms": 125.5,
        "errors": [],
    }

    with patch("app.api.v1.endpoints.knowledge.IngestionService") as mock_ingest_cls:
        mock_ingest = MagicMock()
        mock_ingest.reindex_all_sources = AsyncMock(return_value=mock_reindex_res)
        mock_ingest_cls.return_value = mock_ingest

        res = await async_client.post("/api/v1/knowledge/reindex")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["documents_processed"] == 5
        assert data["documents_indexed"] == 3


@pytest.mark.asyncio
async def test_api_multi_user_isolation(async_client: AsyncClient, test_db: AsyncSession):
    user1 = await create_user(test_db, "user1_iso@example.com")
    user2 = await create_user(test_db, "user2_iso@example.com")

    # Document for user2
    doc_user2 = KnowledgeDocument(
        user_id=user2.id,
        source_type="gmail",
        source_id="u2-msg",
        title="User 2 Confidential",
        content_hash="h_u2",
        status="active",
    )
    test_db.add(doc_user2)
    await test_db.flush()

    chunk_user2 = KnowledgeChunk(
        document_id=doc_user2.id,
        user_id=user2.id,
        chunk_index=0,
        content="Confidential data for user 2 only.",
        embedding=[0.5] * 768,
    )
    test_db.add(chunk_user2)
    await test_db.commit()

    # User 1 calls status
    authenticate_client(async_client, user1)
    status_res = await async_client.get("/api/v1/knowledge/status")
    assert status_res.status_code == 200
    # User 1 should see 0 documents
    assert status_res.json()["total_documents"] == 0
    assert status_res.json()["total_chunks"] == 0
