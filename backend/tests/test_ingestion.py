"""
Unit and integration tests for IngestionService (Milestone 7).
Covers multi-source ingestion (Tasks, Reminders, Gmail, Calendar), SHA-256 deduplication,
atomic chunk replacement, bounded limits, stale/deleted data handling, and rollback on error.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.task import Task
from app.models.reminder import Reminder
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.services.ingestion_service import IngestionService
from app.ai.embeddings.base import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic mock embedding provider for tests."""

    def __init__(self, dimension: int = 768):
        self._dimension = dimension
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-embedding-model"

    @property
    def dimensions(self) -> int:
        return self._dimension

    async def embed_text(self, text: str) -> list[float]:
        self.call_count += 1
        return [0.05] * self._dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.call_count += len(texts)
        return [[0.05] * self._dimension for _ in texts]


@pytest.fixture
def mock_embedder():
    return MockEmbeddingProvider(dimension=768)


@pytest.fixture
def ingestion_service(mock_embedder):
    return IngestionService(embedding_provider=mock_embedder)


@pytest.fixture
async def test_user(test_db: AsyncSession) -> User:
    user = User(email="rag_tester@example.com", full_name="RAG Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_ingest_single_document_success(test_db: AsyncSession, test_user: User, ingestion_service, mock_embedder):
    res = await ingestion_service.ingest_single_document(
        db=test_db,
        user_id=test_user.id,
        source_type="tasks",
        source_id="task-101",
        title="Deploy v1.0",
        content="Deploy v1.0 application to production environment.",
        context_header="[Source: Tasks | Title: Deploy v1.0]",
    )

    assert res["status"] == "indexed"
    assert res["chunks"] > 0
    assert mock_embedder.call_count > 0

    # Verify DB state
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.user_id == test_user.id,
        KnowledgeDocument.source_id == "task-101",
    )
    doc = (await test_db.execute(stmt)).scalar_one()
    assert doc.title == "Deploy v1.0"
    assert doc.status == "active"

    chunk_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
    chunks = (await test_db.execute(chunk_stmt)).scalars().all()
    assert len(chunks) > 0
    assert len(chunks[0].embedding_vector) == 768


@pytest.mark.asyncio
async def test_ingest_deduplication_unchanged_content_skips_embedding(test_db: AsyncSession, test_user: User, ingestion_service, mock_embedder):
    # First ingestion
    await ingestion_service.ingest_single_document(
        db=test_db,
        user_id=test_user.id,
        source_type="tasks",
        source_id="task-102",
        title="Weekly Sync",
        content="Sync meeting notes with team.",
    )
    initial_calls = mock_embedder.call_count
    assert initial_calls > 0

    # Second ingestion with identical content
    res = await ingestion_service.ingest_single_document(
        db=test_db,
        user_id=test_user.id,
        source_type="tasks",
        source_id="task-102",
        title="Weekly Sync",
        content="Sync meeting notes with team.",
    )

    assert res["status"] == "skipped"
    assert res["reason"] == "unchanged_content"
    # Zero additional embedding calls made
    assert mock_embedder.call_count == initial_calls


@pytest.mark.asyncio
async def test_ingest_atomic_replacement_on_content_change(test_db: AsyncSession, test_user: User, ingestion_service, mock_embedder):
    # Initial doc
    await ingestion_service.ingest_single_document(
        db=test_db,
        user_id=test_user.id,
        source_type="tasks",
        source_id="task-103",
        title="Initial Title",
        content="Initial content version 1.",
    )

    doc_stmt = select(KnowledgeDocument).where(KnowledgeDocument.source_id == "task-103")
    doc1 = (await test_db.execute(doc_stmt)).scalar_one()
    initial_hash = doc1.content_hash

    chunk_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc1.id)
    initial_chunk = (await test_db.execute(chunk_stmt)).scalars().first()
    initial_chunk_id = initial_chunk.id

    # Update with new content
    res = await ingestion_service.ingest_single_document(
        db=test_db,
        user_id=test_user.id,
        source_type="tasks",
        source_id="task-103",
        title="Updated Title",
        content="Updated content version 2 with completely different text.",
    )

    assert res["status"] == "indexed"
    doc2 = (await test_db.execute(doc_stmt)).scalar_one()
    assert doc2.content_hash != initial_hash
    assert doc2.title == "Updated Title"

    new_chunks = (await test_db.execute(chunk_stmt)).scalars().all()
    assert len(new_chunks) > 0
    assert new_chunks[0].id != initial_chunk_id
    assert "version 2" in new_chunks[0].content


@pytest.mark.asyncio
async def test_ingest_tasks_from_database(test_db: AsyncSession, test_user: User, ingestion_service):
    # Create 2 tasks for test_user
    task1 = Task(
        user_id=test_user.id,
        title="Review PR #42",
        description="Review backend pull request for milestone 7.",
        status="pending",
        priority="high",
    )
    task2 = Task(
        user_id=test_user.id,
        title="Write Documentation",
        description="Write comprehensive API docs.",
        status="completed",
        priority="medium",
    )
    test_db.add_all([task1, task2])
    await test_db.commit()

    res = await ingestion_service.ingest_tasks(test_db, test_user)
    assert res["processed"] >= 2
    assert res["indexed"] >= 2

    # Verify both are stored in KnowledgeDocument
    stmt = select(func.count(KnowledgeDocument.id)).where(
        KnowledgeDocument.user_id == test_user.id,
        KnowledgeDocument.source_type == "tasks",
    )
    count = (await test_db.execute(stmt)).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_ingest_reminders_from_database(test_db: AsyncSession, test_user: User, ingestion_service):
    rem = Reminder(
        user_id=test_user.id,
        title="Doctor Appointment",
        message="Annual checkup at medical center.",
        remind_at=datetime.now(timezone.utc),
        status="scheduled",
    )
    test_db.add(rem)
    await test_db.commit()

    res = await ingestion_service.ingest_reminders(test_db, test_user)
    assert res["processed"] >= 1
    assert res["indexed"] >= 1

    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.user_id == test_user.id,
        KnowledgeDocument.source_type == "reminders",
        KnowledgeDocument.source_id == rem.id,
    )
    doc = (await test_db.execute(stmt)).scalar_one()
    assert "Doctor Appointment" in doc.title

    chunk_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
    chunks = (await test_db.execute(chunk_stmt)).scalars().all()
    assert "Annual checkup" in chunks[0].content


@pytest.mark.asyncio
async def test_ingest_gmail_messages_mocked(test_db: AsyncSession, test_user: User, ingestion_service):
    mock_messages = [
        {
            "id": "gmail_msg_001",
            "thread_id": "thread_001",
            "subject": "Q3 Budget Review",
            "from_address": "finance@example.com",
            "to_address": "user@example.com",
            "date": "2026-09-15T10:00:00Z",
            "snippet": "Attached is the Q3 financial summary.",
            "body_plain": "Attached is the Q3 financial summary. We are 15% under budget.",
        }
    ]

    with patch("app.services.ingestion_service.GmailService") as mock_gmail_cls:
        mock_gmail = MagicMock()
        mock_gmail.list_messages = AsyncMock(return_value={"messages": mock_messages, "total": 1})
        mock_gmail.get_message = AsyncMock(return_value=mock_messages[0])
        mock_gmail_cls.return_value = mock_gmail

        res = await ingestion_service.ingest_gmail(test_db, test_user)
        assert res["processed"] == 1
        assert res["indexed"] == 1

        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == test_user.id,
            KnowledgeDocument.source_type == "gmail",
            KnowledgeDocument.source_id == "gmail_msg_001",
        )
        doc = (await test_db.execute(stmt)).scalar_one()
        assert doc.title == "Q3 Budget Review"

        chunk_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
        chunks = (await test_db.execute(chunk_stmt)).scalars().all()
        assert "finance@example.com" in chunks[0].content


@pytest.mark.asyncio
async def test_ingest_calendar_events_mocked(test_db: AsyncSession, test_user: User, ingestion_service):
    mock_events = [
        {
            "id": "cal_evt_001",
            "summary": "Design Architecture Sprint",
            "description": "Discussing RAG pipeline and pgvector indexing.",
            "start": {"dateTime": "2026-09-16T14:00:00Z"},
            "end": {"dateTime": "2026-09-16T15:00:00Z"},
            "location": "Room 404",
        }
    ]

    with patch("app.services.ingestion_service.CalendarService") as mock_cal_cls:
        mock_cal = MagicMock()
        mock_cal.list_events = AsyncMock(return_value={"events": mock_events, "total": 1})
        mock_cal_cls.return_value = mock_cal

        res = await ingestion_service.ingest_calendar(test_db, test_user)
        assert res["processed"] == 1
        assert res["indexed"] == 1

        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == test_user.id,
            KnowledgeDocument.source_type == "calendar",
            KnowledgeDocument.source_id == "cal_evt_001",
        )
        doc = (await test_db.execute(stmt)).scalar_one()
        assert doc.title == "Design Architecture Sprint"

        chunk_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
        chunks = (await test_db.execute(chunk_stmt)).scalars().all()
        assert "Room 404" in chunks[0].content


@pytest.mark.asyncio
async def test_ingest_bounded_limits(test_db: AsyncSession, test_user: User, ingestion_service):
    # Create 60 tasks (exceeding MAX_TASKS_PER_INGEST = 50)
    tasks = [
        Task(
            user_id=test_user.id,
            title=f"Task #{i}",
            description=f"Description for task {i}",
            status="pending",
        )
        for i in range(60)
    ]
    test_db.add_all(tasks)
    await test_db.commit()

    res = await ingestion_service.ingest_tasks(test_db, test_user, limit=50)
    assert res["processed"] == 50
    assert res["indexed"] == 50


@pytest.mark.asyncio
async def test_ingest_error_in_embedder_leaves_no_orphan(test_db: AsyncSession, test_user: User):
    class FailingEmbedder(EmbeddingProvider):
        @property
        def provider_name(self) -> str:
            return "failing"

        @property
        def model_name(self) -> str:
            return "failing-model"

        @property
        def dimensions(self) -> int:
            return 768

        async def embed_text(self, text: str) -> list[float]:
            raise RuntimeError("API timeout during embedding")

        async def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("API timeout during embedding")

    service = IngestionService(embedding_provider=FailingEmbedder())

    with pytest.raises(RuntimeError):
        await service.ingest_single_document(
            db=test_db,
            user_id=test_user.id,
            source_type="tasks",
            source_id="task-fail-01",
            title="Will Fail",
            content="This will fail during embedding.",
        )

    # Document should not be committed/active in DB
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.user_id == test_user.id,
        KnowledgeDocument.source_id == "task-fail-01",
    )
    doc = (await test_db.execute(stmt)).scalar_one_or_none()
    assert doc is None


@pytest.mark.asyncio
async def test_mark_document_inactive_on_source_delete(test_db: AsyncSession, test_user: User, ingestion_service):
    # Ingest task
    await ingestion_service.ingest_single_document(
        db=test_db,
        user_id=test_user.id,
        source_type="tasks",
        source_id="task-to-delete",
        title="Temporary Task",
        content="This task is going to be deleted.",
    )

    # Mark inactive
    await ingestion_service.mark_document_inactive(
        db=test_db,
        user_id=test_user.id,
        source_type="tasks",
        source_id="task-to-delete",
    )

    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.user_id == test_user.id,
        KnowledgeDocument.source_id == "task-to-delete",
    )
    doc = (await test_db.execute(stmt)).scalar_one()
    assert doc.status == "deleted"


@pytest.mark.asyncio
async def test_reindex_all_sources_telemetry(test_db: AsyncSession, test_user: User, ingestion_service):
    task = Task(
        user_id=test_user.id,
        title="Test Task for Reindex",
        description="Detailed description for reindex.",
        status="pending",
    )
    test_db.add(task)
    await test_db.commit()

    with patch("app.services.ingestion_service.GmailService") as mock_gmail_cls, \
         patch("app.services.ingestion_service.CalendarService") as mock_cal_cls:
        mock_gmail = MagicMock()
        mock_gmail.list_messages = AsyncMock(return_value={"messages": [], "total": 0})
        mock_gmail_cls.return_value = mock_gmail

        mock_cal = MagicMock()
        mock_cal.list_events = AsyncMock(return_value={"events": [], "total": 0})
        mock_cal_cls.return_value = mock_cal

        res = await ingestion_service.reindex_all_sources(test_db, test_user)
        assert res["status"] in ["completed", "partial_success"]
        assert res["documents_processed"] >= 1
        assert res["documents_indexed"] >= 1
        assert "duration_ms" in res
