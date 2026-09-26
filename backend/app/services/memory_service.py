"""
Memory Service for Long-Term Personal Memory & Personalization (Milestone 11).
Enforces privacy-first defaults, deterministic relevance scoring, secret scanning heuristic,
atomic PostgreSQL upserts, and strict multi-user isolation.
"""
import re
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, func, and_, or_, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.metrics import metrics_registry
from app.models.user_memory import UserMemory
from app.models.user_preference import UserPreference
from app.schemas.memory import MemoryCreateRequest, MemoryUpdateRequest

logger = logging.getLogger(__name__)


class SecretDetectedError(ValueError):
    """Raised when heuristic secret scanner detects potentially sensitive credential material."""
    pass


class MemoryService:
    """
    Manages long-term personal memories with privacy-first opt-in default,
    deterministic relevance scoring, and strict multi-user isolation.
    """

    # First-line heuristic regex patterns for credential and secret detection
    _SECRET_PATTERNS = [
        # AWS Access Key ID
        re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"),
        # OpenAI API Key
        re.compile(r"\bsk-[a-zA-Z0-9_\-]{20,}\b"),
        # Google API Key
        re.compile(r"\bAIza[0-9A-Za-z\-_]{30,45}\b"),
        # GitHub Personal Access Token
        re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}\b"),
        # Slack Token
        re.compile(r"\bxox[baprs]-[0-9]{10,}-[0-9]{10,}-[a-zA-Z0-9]{24,}\b"),
        # JWT Token pattern (three base64url segments separated by dots)
        re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"),
        # Private Key Header
        re.compile(r"-----BEGIN\s+.*?\s*KEY-----", re.IGNORECASE),
        # Explicit password or secret assignment heuristic (e.g., password = "mySecretPassword123")
        re.compile(r"(?i)\b(?:password|passwd|secret_key|api_secret|auth_token|client_secret)\s*[:=]\s*['\"][^\s'\"]{8,}['\"]"),
    ]

    @classmethod
    def _is_luhn_valid(cls, card_number_str: str) -> bool:
        """Helper to validate potential credit card numbers via Luhn algorithm."""
        digits = [int(c) for c in card_number_str if c.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        checksum = 0
        reversed_digits = digits[::-1]
        for i, digit in enumerate(reversed_digits):
            if i % 2 == 1:
                doubled = digit * 2
                checksum += (doubled - 9) if doubled > 9 else doubled
            else:
                checksum += digit
        return checksum % 10 == 0

    @classmethod
    def scan_for_secrets(cls, text: str) -> Tuple[bool, Optional[str]]:
        """
        First-line heuristic secret scanner.
        Scans text for obvious API keys, JWTs, private keys, passwords, and credit card numbers.
        Returns (has_secret, secret_category).
        Does NOT log or echo the secret value.
        """
        if not text or not isinstance(text, str):
            return False, None

        for pattern in cls._SECRET_PATTERNS:
            if pattern.search(text):
                return True, "credential_or_key"

        # Check for potential credit card numbers
        candidate_numbers = re.findall(r"(?:\d[ -]*){13,19}", text)
        for cand in candidate_numbers:
            clean = re.sub(r"\D", "", cand)
            if 13 <= len(clean) <= 19 and cls._is_luhn_valid(clean):
                return True, "payment_card_number"

        return False, None

    @classmethod
    async def is_memory_enabled_for_user(cls, db: AsyncSession, user_id: str) -> bool:
        """
        Checks if long-term memory is explicitly enabled for the given user.
        Privacy-conscious default: False until explicitly enabled in UserPreference.
        """
        stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        result = await db.execute(stmt)
        pref = result.scalars().first()
        if not pref:
            return settings.MEMORY_ENABLED_DEFAULT
        return bool(pref.memory_enabled)

    @classmethod
    async def create_or_upsert_memory(
        cls,
        db: AsyncSession,
        user_id: str,
        memory_in: MemoryCreateRequest,
    ) -> UserMemory:
        """
        Creates or updates a memory atomically on conflict (user_id, category, key).
        Enforces heuristic secret scanning, provenance tagging, and length bounds.
        """
        # 1. First-line heuristic secret scanning
        has_secret_val, cat_val = cls.scan_for_secrets(memory_in.value)
        if has_secret_val:
            metrics_registry.inc_counter("memory_operations_total", labels={"action": "secret_rejected"})
            logger.warning("Rejected memory write containing detected secret category=%s for user_id=%s", cat_val, user_id[:8])
            raise SecretDetectedError("Memory content was rejected because it contains sensitive credentials, keys, or passwords.")

        if memory_in.description:
            has_secret_desc, cat_desc = cls.scan_for_secrets(memory_in.description)
            if has_secret_desc:
                metrics_registry.inc_counter("memory_operations_total", labels={"action": "secret_rejected"})
                logger.warning("Rejected memory write with secret in description for user_id=%s", user_id[:8])
                raise SecretDetectedError("Memory description was rejected because it contains sensitive credentials.")

        # 2. Derive confidence and confirmation status based on source provenance
        confidence_map = {
            "EXPLICIT": 1.0,
            "HIGH_CONFIDENCE": 0.85,
            "MEDIUM_CONFIDENCE": 0.65,
            "LOW_CONFIDENCE": 0.40,
        }

        source = memory_in.source or "explicit_user_request"
        if source in ("explicit_user_request", "user_ui"):
            confidence = "EXPLICIT"
            confidence_score = 1.0
            explicitly_confirmed = True
            active = True
        elif source == "agent_inference":
            confidence = memory_in.confidence or "MEDIUM_CONFIDENCE"
            confidence_score = confidence_map.get(confidence, 0.65)
            explicitly_confirmed = memory_in.explicitly_confirmed or False
            active = explicitly_confirmed  # Inferred memories stay inactive until confirmed
        else:
            confidence = memory_in.confidence or "EXPLICIT"
            confidence_score = confidence_map.get(confidence, 1.0)
            explicitly_confirmed = memory_in.explicitly_confirmed or False
            active = True

        now = datetime.now(timezone.utc)
        clean_key = memory_in.key.strip()[:settings.MEMORY_MAX_KEY_LENGTH]
        clean_val = memory_in.value.strip()[:settings.MEMORY_MAX_VALUE_LENGTH]
        clean_desc = memory_in.description.strip()[:500] if memory_in.description else None

        # 3. Dialect-aware Upsert
        dialect_name = ""
        try:
            bind = db.get_bind()
            if bind:
                dialect_name = getattr(bind.dialect, "name", "")
        except Exception:
            pass

        if not dialect_name and "postgres" in str(settings.DATABASE_URL).lower():
            dialect_name = "postgresql"

        if dialect_name == "postgresql":
            insert_stmt = insert(UserMemory).values(
                user_id=user_id,
                category=memory_in.category,
                key=clean_key,
                value=clean_val,
                description=clean_desc,
                confidence=confidence,
                confidence_score=confidence_score,
                source=source,
                source_reference=memory_in.source_reference,
                explicitly_confirmed=explicitly_confirmed,
                active=active,
                last_confirmed_at=now,
                memory_metadata=memory_in.memory_metadata or {},
                created_at=now,
                updated_at=now,
            )

            upsert_stmt = insert_stmt.on_conflict_do_update(
                constraint="uq_user_memory_category_key",
                set_={
                    "value": clean_val,
                    "description": clean_desc,
                    "confidence": confidence,
                    "confidence_score": confidence_score,
                    "source": source,
                    "source_reference": memory_in.source_reference,
                    "explicitly_confirmed": explicitly_confirmed,
                    "active": active,
                    "last_confirmed_at": now,
                    "memory_metadata": memory_in.memory_metadata or {},
                    "updated_at": now,
                },
            ).returning(UserMemory)

            result = await db.execute(upsert_stmt)
            await db.commit()
            memory = result.scalars().first()
        else:
            stmt = select(UserMemory).where(
                and_(
                    UserMemory.user_id == user_id,
                    UserMemory.category == memory_in.category,
                    UserMemory.key == clean_key,
                )
            )
            existing = (await db.execute(stmt)).scalars().first()
            if existing:
                existing.value = clean_val
                existing.description = clean_desc
                existing.confidence = confidence
                existing.confidence_score = confidence_score
                existing.source = source
                existing.source_reference = memory_in.source_reference
                existing.explicitly_confirmed = explicitly_confirmed
                existing.active = active
                existing.last_confirmed_at = now
                existing.memory_metadata = memory_in.memory_metadata or {}
                existing.updated_at = now
                await db.commit()
                await db.refresh(existing)
                memory = existing
            else:
                new_mem = UserMemory(
                    user_id=user_id,
                    category=memory_in.category,
                    key=clean_key,
                    value=clean_val,
                    description=clean_desc,
                    confidence=confidence,
                    confidence_score=confidence_score,
                    source=source,
                    source_reference=memory_in.source_reference,
                    explicitly_confirmed=explicitly_confirmed,
                    active=active,
                    last_confirmed_at=now,
                    memory_metadata=memory_in.memory_metadata or {},
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_mem)
                await db.commit()
                await db.refresh(new_mem)
                memory = new_mem

        metrics_registry.inc_counter("memory_operations_total", labels={"action": "upsert"})
        logger.info("Upserted memory id=%s category=%s key=%s for user_id=%s", memory.id[:8], memory.category, memory.key, user_id[:8])

        try:
            from app.services.personalization_service import PersonalizationService
            await PersonalizationService.invalidate_user_cache(user_id)
        except Exception:
            pass

        return memory

    @classmethod
    async def get_memory(
        cls,
        db: AsyncSession,
        user_id: str,
        memory_id: str,
    ) -> Optional[UserMemory]:
        """Retrieves a specific memory by ID enforcing strict user isolation."""
        stmt = select(UserMemory).where(
            and_(UserMemory.id == memory_id, UserMemory.user_id == user_id)
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @classmethod
    async def list_memories(
        cls,
        db: AsyncSession,
        user_id: str,
        category: Optional[str] = None,
        active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[UserMemory], int]:
        """Lists user memories with optional filtering and pagination."""
        filters = [UserMemory.user_id == user_id]
        if category:
            filters.append(UserMemory.category == category)
        if active is not None:
            filters.append(UserMemory.active == active)

        count_stmt = select(func.count(UserMemory.id)).where(and_(*filters))
        total = (await db.execute(count_stmt)).scalar() or 0

        lim = min(max(limit, 1), 100)
        off = max(offset, 0)
        stmt = (
            select(UserMemory)
            .where(and_(*filters))
            .order_by(UserMemory.category.asc(), UserMemory.key.asc(), UserMemory.updated_at.desc())
            .limit(lim)
            .offset(off)
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        metrics_registry.inc_counter("memory_operations_total", labels={"action": "list"})
        return items, total

    @classmethod
    async def search_memories(
        cls,
        db: AsyncSession,
        user_id: str,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[UserMemory]:
        """
        Searches user memories matching query terms across key, value, and description.
        Applies deterministic relevance scoring and ordering.
        """
        clean_query = query.strip().lower()
        if not clean_query:
            return []

        filters = [UserMemory.user_id == user_id]
        if category:
            filters.append(UserMemory.category == category)

        # Basic SQL search filter
        search_filter = or_(
            UserMemory.key.ilike(f"%{clean_query}%"),
            UserMemory.value.ilike(f"%{clean_query}%"),
            UserMemory.description.ilike(f"%{clean_query}%"),
        )
        filters.append(search_filter)

        stmt = select(UserMemory).where(and_(*filters))
        result = await db.execute(stmt)
        candidates = list(result.scalars().all())

        # Deterministic scoring
        tokens = [t for t in re.split(r"\W+", clean_query) if t]
        now = datetime.now(timezone.utc)

        def _score(m: UserMemory) -> float:
            score = 0.0
            m_key_lower = m.key.lower()
            m_val_lower = m.value.lower()
            m_desc_lower = (m.description or "").lower()

            if clean_query in m_key_lower:
                score += 10.0
            if clean_query in m_val_lower:
                score += 5.0
            if category and m.category == category:
                score += 5.0

            # Token overlaps
            for token in tokens:
                if token in m_key_lower:
                    score += 3.0
                if token in m_val_lower:
                    score += 2.0
                if token in m_desc_lower:
                    score += 1.0

            score += (4.0 if m.explicitly_confirmed else 1.0)
            score += (m.confidence_score * 2.0)
            last_conf = m.last_confirmed_at
            if last_conf is not None:
                if last_conf.tzinfo is None:
                    last_conf = last_conf.replace(tzinfo=timezone.utc)
                if (now - last_conf).days < 30:
                    score += 1.0
            return score

        scored = [(_score(m), m) for m in candidates]
        def _sort_key(pair):
            score, m = pair
            last_conf = m.last_confirmed_at
            if last_conf is not None and last_conf.tzinfo is None:
                last_conf = last_conf.replace(tzinfo=timezone.utc)
            ts = last_conf.timestamp() if last_conf else 0.0
            return (-score, -m.confidence_score, -ts, m.key)

        scored.sort(key=_sort_key)

        lim = min(max(limit, 1), settings.MEMORY_SEARCH_LIMIT)
        metrics_registry.inc_counter("memory_operations_total", labels={"action": "search"})
        return [m for _, m in scored[:lim]]

    @classmethod
    async def get_relevant_memory_context(
        cls,
        db: AsyncSession,
        user_id: str,
        query: str,
        top_k: int = 10,
    ) -> List[UserMemory]:
        """
        Retrieves top relevant active memories for AgentOrchestrator context injection.
        Enforces privacy gate: returns [] immediately if memory_enabled is False.
        Bounds output by max item count (10) and max character length (2,000 chars).
        """
        # 1. Privacy gate check
        enabled = await cls.is_memory_enabled_for_user(db=db, user_id=user_id)
        if not enabled:
            return []

        # 2. Fetch all active memories for user
        stmt = (
            select(UserMemory)
            .where(and_(UserMemory.user_id == user_id, UserMemory.active == True))
        )
        result = await db.execute(stmt)
        active_memories = list(result.scalars().all())
        if not active_memories:
            return []

        # 3. Deterministic scoring
        clean_query = query.strip().lower()
        tokens = [t for t in re.split(r"\W+", clean_query) if t]
        now = datetime.now(timezone.utc)

        def _score(m: UserMemory) -> float:
            score = 0.0
            m_key_lower = m.key.lower()
            m_val_lower = m.value.lower()
            m_desc_lower = (m.description or "").lower()

            if clean_query and clean_query in m_key_lower:
                score += 10.0
            if clean_query and clean_query in m_val_lower:
                score += 5.0

            for token in tokens:
                if token in m_key_lower:
                    score += 3.0
                if token in m_val_lower:
                    score += 2.0
                if token in m_desc_lower:
                    score += 1.0

            score += (4.0 if m.explicitly_confirmed else 1.0)
            score += (m.confidence_score * 2.0)
            last_conf = m.last_confirmed_at
            if last_conf is not None:
                if last_conf.tzinfo is None:
                    last_conf = last_conf.replace(tzinfo=timezone.utc)
                if (now - last_conf).days < 30:
                    score += 1.0
            return score

        scored = [(_score(m), m) for m in active_memories]
        def _sort_context_key(p):
            score, m = p
            last_conf = m.last_confirmed_at
            if last_conf is not None and last_conf.tzinfo is None:
                last_conf = last_conf.replace(tzinfo=timezone.utc)
            ts = last_conf.timestamp() if last_conf else 0.0
            return (-score, -m.confidence_score, -ts, m.key)

        # Stable tie-breaking: score desc, confidence_score desc, last_confirmed_at desc, key asc
        scored.sort(key=_sort_context_key)

        max_items = min(top_k, settings.MEMORY_MAX_ITEMS_PER_CONTEXT)
        selected: List[UserMemory] = []
        total_chars = 0

        for _, m in scored:
            # Format candidate line length estimation
            line_len = len(m.category) + len(m.key) + len(m.value[:500]) + 50
            if total_chars + line_len > settings.MEMORY_MAX_CONTEXT_CHARS:
                break
            selected.append(m)
            total_chars += line_len
            if len(selected) >= max_items:
                break

        metrics_registry.inc_counter("memory_operations_total", labels={"action": "context_retrieval"})
        return selected

    @classmethod
    async def update_memory(
        cls,
        db: AsyncSession,
        user_id: str,
        memory_id: str,
        update_in: MemoryUpdateRequest,
    ) -> Optional[UserMemory]:
        """Updates an existing memory with validation and secret scanning."""
        memory = await cls.get_memory(db=db, user_id=user_id, memory_id=memory_id)
        if not memory:
            return None

        if update_in.value is not None:
            has_sec, cat = cls.scan_for_secrets(update_in.value)
            if has_sec:
                metrics_registry.inc_counter("memory_operations_total", labels={"action": "secret_rejected"})
                raise SecretDetectedError("Updated memory content was rejected because it contains sensitive credentials.")
            memory.value = update_in.value.strip()[:settings.MEMORY_MAX_VALUE_LENGTH]

        if update_in.description is not None:
            has_sec_desc, cat_desc = cls.scan_for_secrets(update_in.description)
            if has_sec_desc:
                metrics_registry.inc_counter("memory_operations_total", labels={"action": "secret_rejected"})
                raise SecretDetectedError("Updated memory description contains sensitive credentials.")
            memory.description = update_in.description.strip()[:500]

        if update_in.category is not None:
            memory.category = update_in.category

        if update_in.active is not None:
            memory.active = update_in.active

        if update_in.explicitly_confirmed is not None:
            memory.explicitly_confirmed = update_in.explicitly_confirmed
            if update_in.explicitly_confirmed:
                memory.last_confirmed_at = datetime.now(timezone.utc)
                if memory.source == "agent_inference" and update_in.confidence is None:
                    memory.confidence = "HIGH_CONFIDENCE"
                    memory.confidence_score = 0.85

        if update_in.confidence is not None:
            memory.confidence = update_in.confidence
            conf_map = {"EXPLICIT": 1.0, "HIGH_CONFIDENCE": 0.85, "MEDIUM_CONFIDENCE": 0.65, "LOW_CONFIDENCE": 0.40}
            memory.confidence_score = conf_map.get(update_in.confidence, 1.0)

        memory.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(memory)

        metrics_registry.inc_counter("memory_operations_total", labels={"action": "update"})
        try:
            from app.services.personalization_service import PersonalizationService
            await PersonalizationService.invalidate_user_cache(user_id)
        except Exception:
            pass
        return memory

    @classmethod
    async def deactivate_memory(
        cls,
        db: AsyncSession,
        user_id: str,
        memory_id: str,
    ) -> Optional[UserMemory]:
        """Soft-deactivates a memory without permanently deleting data."""
        memory = await cls.get_memory(db=db, user_id=user_id, memory_id=memory_id)
        if not memory:
            return None
        memory.active = False
        memory.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(memory)

        metrics_registry.inc_counter("memory_operations_total", labels={"action": "deactivate"})
        try:
            from app.services.personalization_service import PersonalizationService
            await PersonalizationService.invalidate_user_cache(user_id)
        except Exception:
            pass
        return memory

    @classmethod
    async def delete_memory(
        cls,
        db: AsyncSession,
        user_id: str,
        memory_id: str,
    ) -> bool:
        """Permanently deletes a memory with exact user ownership verification."""
        stmt = delete(UserMemory).where(
            and_(UserMemory.id == memory_id, UserMemory.user_id == user_id)
        )
        result = await db.execute(stmt)
        await db.commit()

        deleted = result.rowcount > 0
        if deleted:
            metrics_registry.inc_counter("memory_operations_total", labels={"action": "delete"})
            try:
                from app.services.personalization_service import PersonalizationService
                await PersonalizationService.invalidate_user_cache(user_id)
            except Exception:
                pass
        return deleted

    @classmethod
    async def get_memory_stats(
        cls,
        db: AsyncSession,
        user_id: str,
    ) -> Dict[str, Any]:
        """Computes memory aggregation metrics for dashboard inspection."""
        enabled = await cls.is_memory_enabled_for_user(db=db, user_id=user_id)

        stmt = select(UserMemory).where(UserMemory.user_id == user_id)
        result = await db.execute(stmt)
        memories = list(result.scalars().all())

        total = len(memories)
        active_cnt = sum(1 for m in memories if m.active)
        inactive_cnt = total - active_cnt

        by_cat: Dict[str, int] = {}
        by_conf: Dict[str, int] = {}

        for m in memories:
            by_cat[m.category] = by_cat.get(m.category, 0) + 1
            by_conf[m.confidence] = by_conf.get(m.confidence, 0) + 1

        return {
            "total_memories": total,
            "active_memories": active_cnt,
            "inactive_memories": inactive_cnt,
            "memory_enabled": enabled,
            "by_category": by_cat,
            "by_confidence": by_conf,
        }
