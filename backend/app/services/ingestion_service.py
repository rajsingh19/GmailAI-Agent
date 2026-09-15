"""
Ingestion Service for Personal Knowledge RAG (Milestone 7).
Coordinates authorized data gathering, content hashing, deduplication, chunking, and atomic embedding storage.
"""
import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.models.task import Task
from app.models.reminder import Reminder
from app.services.chunking_service import ChunkingService
from app.services.task_service import TaskService
from app.services.reminder_service import ReminderService
from app.services.gmail_service import (
    GmailService,
    GmailNotConnectedError,
    GmailAuthenticationError,
    GmailServiceError,
)
from app.services.calendar_service import (
    CalendarService,
    CalendarNotConnectedError,
    CalendarAuthenticationError,
    CalendarScopeMissingError,
    CalendarServiceError,
)
from app.ai.embeddings.base import EmbeddingProvider
from app.ai.embeddings.gemini_embeddings import GeminiEmbeddingProvider

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Manages the controlled, bounded ingestion and reindexing of personal knowledge sources.
    Enforces strict user isolation, deduplication via SHA-256 hashes, and atomic chunk updates.
    """

    def __init__(self, embedding_provider: Optional[EmbeddingProvider] = None):
        self.embedder = embedding_provider or GeminiEmbeddingProvider()

    async def reindex_all_sources(
        self,
        db: AsyncSession,
        user: User,
    ) -> Dict[str, Any]:
        """
        Executes bounded synchronous reindexing across all authorized sources for the user.
        Returns detailed ingestion telemetry.
        """
        start_time = time.perf_counter()
        logger.info("Starting knowledge reindex for user_id=%s (email=%s)", user.id[:8], user.email)

        total_processed = 0
        total_indexed = 0
        total_skipped = 0
        total_chunks = 0
        errors: List[str] = []

        # 1. Ingest Tasks
        try:
            task_res = await self.ingest_tasks(db, user)
            total_processed += task_res["processed"]
            total_indexed += task_res["indexed"]
            total_skipped += task_res["skipped"]
            total_chunks += task_res["chunks"]
        except Exception as exc:
            logger.exception("Error ingesting tasks: %s", exc)
            errors.append(f"Tasks ingestion error: {exc}")

        # 2. Ingest Reminders
        try:
            rem_res = await self.ingest_reminders(db, user)
            total_processed += rem_res["processed"]
            total_indexed += rem_res["indexed"]
            total_skipped += rem_res["skipped"]
            total_chunks += rem_res["chunks"]
        except Exception as exc:
            logger.exception("Error ingesting reminders: %s", exc)
            errors.append(f"Reminders ingestion error: {exc}")

        # 3. Ingest Gmail Messages (if connected)
        try:
            gmail_res = await self.ingest_gmail_messages(db, user)
            total_processed += gmail_res["processed"]
            total_indexed += gmail_res["indexed"]
            total_skipped += gmail_res["skipped"]
            total_chunks += gmail_res["chunks"]
        except (GmailNotConnectedError, GmailAuthenticationError) as exc:
            logger.info("Gmail skipped for user_id=%s: %s", user.id[:8], exc)
        except Exception as exc:
            logger.exception("Error ingesting Gmail messages: %s", exc)
            errors.append(f"Gmail ingestion error: {exc}")

        # 4. Ingest Calendar Events (if connected)
        try:
            cal_res = await self.ingest_calendar_events(db, user)
            total_processed += cal_res["processed"]
            total_indexed += cal_res["indexed"]
            total_skipped += cal_res["skipped"]
            total_chunks += cal_res["chunks"]
        except (CalendarNotConnectedError, CalendarAuthenticationError, CalendarScopeMissingError) as exc:
            logger.info("Calendar skipped for user_id=%s: %s", user.id[:8], exc)
        except Exception as exc:
            logger.exception("Error ingesting Calendar events: %s", exc)
            errors.append(f"Calendar ingestion error: {exc}")

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "Reindex completed for user_id=%s in %.2fms (processed=%d, indexed=%d, skipped=%d, chunks=%d)",
            user.id[:8],
            duration_ms,
            total_processed,
            total_indexed,
            total_skipped,
            total_chunks,
        )

        return {
            "status": "completed" if not errors else "partial_success",
            "documents_processed": total_processed,
            "documents_indexed": total_indexed,
            "documents_skipped": total_skipped,
            "chunks_created": total_chunks,
            "duration_ms": duration_ms,
            "errors": errors,
        }

    async def ingest_single_document(
        self,
        db: AsyncSession,
        user_id: str,
        source_type: str,
        source_id: str,
        title: str,
        content: str,
        context_header: Optional[str] = None,
        doc_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Atomically processes and indexes a single source document.
        Uses SHA-256 deduplication to skip unchanged content.
        """
        clean_content = content.strip()
        if not clean_content:
            return {"status": "skipped", "reason": "empty_content", "chunks": 0}

        content_hash = ChunkingService.compute_content_hash(clean_content)
        metadata = doc_metadata or {}

        # 1. Check existing document for deduplication
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.user_id == user_id,
            KnowledgeDocument.source_type == source_type,
            KnowledgeDocument.source_id == source_id,
        )
        result = await db.execute(stmt)
        existing_doc = result.scalar_one_or_none()

        if existing_doc and existing_doc.status == "active" and existing_doc.content_hash == content_hash:
            # Unchanged content -> Skip re-embedding
            return {"status": "skipped", "reason": "unchanged_content", "chunks": 0}

        # 2. Chunk text
        chunks_data = ChunkingService.chunk_text(
            clean_content,
            context_header=context_header or f"[Source: {source_type.capitalize()} | Title: {title}]",
        )
        if not chunks_data:
            return {"status": "skipped", "reason": "no_chunks_generated", "chunks": 0}

        chunk_texts = [c["content"] for c in chunks_data]

        # 3. Generate embeddings
        embeddings = await self.embedder.embed_documents(chunk_texts)

        # 4. Atomic Database Update
        now = datetime.now(timezone.utc)
        if existing_doc:
            doc = existing_doc
            doc.title = title
            doc.content_hash = content_hash
            doc.doc_metadata = metadata
            doc.status = "active"
            doc.indexed_at = now
            doc.updated_at = now

            # Delete old chunks directly
            await db.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
            )
        else:
            doc = KnowledgeDocument(
                user_id=user_id,
                source_type=source_type,
                source_id=source_id,
                title=title,
                content_hash=content_hash,
                doc_metadata=metadata,
                status="active",
                indexed_at=now,
            )
            db.add(doc)
            await db.flush()  # Obtain doc.id

        # Insert new chunks
        for idx, (chk, emb) in enumerate(zip(chunks_data, embeddings)):
            chunk_row = KnowledgeChunk(
                document_id=doc.id,
                user_id=user_id,
                chunk_index=idx,
                content=chk["content"],
                embedding=emb,
                token_count=chk["token_count"],
                chunk_metadata={
                    "source_type": source_type,
                    "source_id": source_id,
                    "title": title,
                    **metadata,
                },
            )
            db.add(chunk_row)

        await db.commit()
        return {"status": "indexed", "chunks": len(chunks_data)}

    async def ingest_tasks(self, db: AsyncSession, user: User, limit: Optional[int] = None) -> Dict[str, int]:
        """Ingests user tasks up to MAX_TASKS_PER_INGEST."""
        max_limit = limit or settings.MAX_TASKS_PER_INGEST
        tasks, _ = await TaskService.list_tasks(
            db=db,
            user_id=user.id,
            limit=max_limit,
        )

        processed = 0
        indexed = 0
        skipped = 0
        chunks = 0

        for task in tasks:
            processed += 1
            content = (
                f"Task: {task.title}\n"
                f"Status: {task.status}\n"
                f"Priority: {task.priority}\n"
                f"Due: {task.due_at.isoformat() if task.due_at else 'None'}\n"
                f"Description: {task.description or 'None'}"
            )
            res = await self.ingest_single_document(
                db=db,
                user_id=user.id,
                source_type="tasks",
                source_id=task.id,
                title=task.title,
                content=content,
                context_header=f"[Source: Task | Status: {task.status} | Priority: {task.priority}]",
                doc_metadata={"priority": task.priority, "status": task.status},
            )
            if res["status"] == "indexed":
                indexed += 1
                chunks += res["chunks"]
            else:
                skipped += 1

        return {"processed": processed, "indexed": indexed, "skipped": skipped, "chunks": chunks}

    async def ingest_reminders(self, db: AsyncSession, user: User, limit: Optional[int] = None) -> Dict[str, int]:
        """Ingests user reminders up to MAX_REMINDERS_PER_INGEST."""
        max_limit = limit or settings.MAX_REMINDERS_PER_INGEST
        reminders, _ = await ReminderService.list_reminders(
            db=db,
            user_id=user.id,
            limit=max_limit,
        )

        processed = 0
        indexed = 0
        skipped = 0
        chunks = 0

        for rem in reminders:
            processed += 1
            content = (
                f"Reminder: {rem.title}\n"
                f"Message: {rem.message or 'None'}\n"
                f"Status: {rem.status}\n"
                f"Remind At: {rem.remind_at.isoformat() if rem.remind_at else 'None'}\n"
                f"Recurrence: {rem.recurrence_rule or 'None'}"
            )
            res = await self.ingest_single_document(
                db=db,
                user_id=user.id,
                source_type="reminders",
                source_id=rem.id,
                title=rem.title,
                content=content,
                context_header=f"[Source: Reminder | Status: {rem.status}]",
                doc_metadata={"status": rem.status},
            )
            if res["status"] == "indexed":
                indexed += 1
                chunks += res["chunks"]
            else:
                skipped += 1

        return {"processed": processed, "indexed": indexed, "skipped": skipped, "chunks": chunks}

    async def ingest_gmail_messages(self, db: AsyncSession, user: User, limit: Optional[int] = None) -> Dict[str, int]:
        """Ingests recent Gmail messages up to MAX_GMAIL_MESSAGES_PER_INGEST using message-level semantics."""
        max_limit = limit or settings.MAX_GMAIL_MESSAGES_PER_INGEST
        gmail_service = GmailService(db=db, user=user)
        list_resp = await gmail_service.list_messages(max_results=max_limit)

        if isinstance(list_resp, dict):
            msg_summaries = list_resp.get("messages", [])
        elif hasattr(list_resp, "messages"):
            msg_summaries = list_resp.messages
        else:
            msg_summaries = []

        processed = 0
        indexed = 0
        skipped = 0
        chunks = 0

        for item in msg_summaries:
            processed += 1
            msg_id = item.get("id") if isinstance(item, dict) else item.id
            try:
                msg_detail = await gmail_service.get_message(msg_id)
                if isinstance(msg_detail, dict):
                    subject = msg_detail.get("subject") or "(No Subject)"
                    sender = msg_detail.get("from_address") or msg_detail.get("sender") or "Unknown"
                    date_val = msg_detail.get("date") or msg_detail.get("timestamp") or ""
                    recipients = msg_detail.get("recipients") or [msg_detail.get("to_address", "")]
                    recipients_str = ", ".join(r for r in recipients if r)
                    body_text = msg_detail.get("body_plain") or msg_detail.get("snippet") or ""
                    thread_id = msg_detail.get("thread_id")
                else:
                    subject = msg_detail.subject or "(No Subject)"
                    sender = msg_detail.sender or "Unknown"
                    date_val = str(msg_detail.timestamp or "")
                    recipients_str = ", ".join(msg_detail.recipients or [])
                    body_text = msg_detail.body_plain or msg_detail.body_html_text or msg_detail.snippet or ""
                    thread_id = msg_detail.thread_id

                content = (
                    f"Subject: {subject}\n"
                    f"From: {sender}\n"
                    f"Date: {date_val}\n"
                    f"Recipients: {recipients_str}\n\n"
                    f"{body_text}"
                )
                res = await self.ingest_single_document(
                    db=db,
                    user_id=user.id,
                    source_type="gmail",
                    source_id=msg_id,
                    title=subject,
                    content=content,
                    context_header=f"[Source: Gmail | From: {sender} | Date: {date_val}]",
                    doc_metadata={
                        "sender": sender,
                        "timestamp": date_val,
                        "thread_id": thread_id,
                    },
                )
                if res["status"] == "indexed":
                    indexed += 1
                    chunks += res["chunks"]
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning("Failed to ingest Gmail message %s: %s", msg_id, exc)

        return {"processed": processed, "indexed": indexed, "skipped": skipped, "chunks": chunks}

    async def ingest_calendar_events(self, db: AsyncSession, user: User, limit: Optional[int] = None) -> Dict[str, int]:
        """Ingests recent Calendar events up to MAX_CALENDAR_EVENTS_PER_INGEST."""
        max_limit = limit or settings.MAX_CALENDAR_EVENTS_PER_INGEST
        cal_service = CalendarService(db=db, user=user)
        events_resp = await cal_service.list_events(
            calendar_id="primary",
            max_results=max_limit,
        )

        if isinstance(events_resp, dict):
            event_items = events_resp.get("events", [])
        elif hasattr(events_resp, "events"):
            event_items = events_resp.events
        else:
            event_items = []

        processed = 0
        indexed = 0
        skipped = 0
        chunks = 0

        for item in event_items:
            processed += 1
            if isinstance(item, dict):
                evt_id = item.get("id", "")
                summary = item.get("summary") or "(No Title)"
                start_val = item.get("start", {}).get("dateTime") if isinstance(item.get("start"), dict) else str(item.get("start", ""))
                end_val = item.get("end", {}).get("dateTime") if isinstance(item.get("end"), dict) else str(item.get("end", ""))
                location = item.get("location") or "N/A"
                description = item.get("description") or "N/A"
            else:
                evt_id = item.id
                summary = item.summary or "(No Title)"
                start_val = str(item.start)
                end_val = str(item.end)
                location = item.location or "N/A"
                description = item.description or "N/A"

            content = (
                f"Event: {summary}\n"
                f"Start: {start_val}\n"
                f"End: {end_val}\n"
                f"Location: {location}\n"
                f"Description:\n{description}"
            )
            res = await self.ingest_single_document(
                db=db,
                user_id=user.id,
                source_type="calendar",
                source_id=evt_id,
                title=summary,
                content=content,
                context_header=f"[Source: Calendar | Time: {start_val} to {end_val}]",
                doc_metadata={
                    "start": start_val,
                    "end": end_val,
                    "location": location,
                },
            )
            if res["status"] == "indexed":
                indexed += 1
                chunks += res["chunks"]
            else:
                skipped += 1

        return {"processed": processed, "indexed": indexed, "skipped": skipped, "chunks": chunks}

    # Method aliases for convenience
    ingest_gmail = ingest_gmail_messages
    ingest_calendar = ingest_calendar_events

    async def mark_source_deleted(
        self,
        db: AsyncSession,
        user_id: str,
        source_type: str,
        source_id: str,
    ) -> bool:
        """
        Marks a source document and its chunks as deleted when deleted from the source service.
        """
        stmt = (
            update(KnowledgeDocument)
            .where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.source_type == source_type,
                KnowledgeDocument.source_id == source_id,
            )
            .values(status="deleted", updated_at=datetime.now(timezone.utc))
        )
        res = await db.execute(stmt)
        await db.commit()
        return res.rowcount > 0

    mark_document_inactive = mark_source_deleted
