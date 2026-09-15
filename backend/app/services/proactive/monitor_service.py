"""
Proactive Monitor Service (Milestone 8).
Coordinates periodic proactive evaluation across active users.
Enforces multi-user isolation, global LLM budget limits, and graceful error handling.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.user_preference import UserPreference
from app.models.notification import Notification
from app.services.notification_service import NotificationService
from app.services.proactive.detectors import (
    CalendarDetector,
    TaskDetector,
    ReminderDetector,
    GmailDetector,
    ProactiveRAGEnricher,
)
from app.services.proactive.decision_engine import ProactiveDecisionEngine

logger = logging.getLogger(__name__)

# Hard Limits for Cost and Safety Control
MAX_LLM_CALLS_PER_USER_CYCLE = 1
MAX_LLM_CALLS_PER_GLOBAL_CYCLE = 5
PROACTIVE_EVALUATION_TIMEOUT_SECONDS = 30.0
PROACTIVE_ADVISORY_LOCK_ID = 84920184



class ProactiveMonitorService:
    """
    Central background coordinator for Milestone 8 Proactive Monitoring.
    Dispatches detectors for each opted-in user with strict timeout and cost controls.
    """

    _instance: Optional["ProactiveMonitorService"] = None

    def __init__(
        self,
        calendar_detector: Optional[CalendarDetector] = None,
        task_detector: Optional[TaskDetector] = None,
        reminder_detector: Optional[ReminderDetector] = None,
        gmail_detector: Optional[GmailDetector] = None,
        rag_enricher: Optional[ProactiveRAGEnricher] = None,
        decision_engine: Optional[ProactiveDecisionEngine] = None,
    ):
        self.calendar_detector = calendar_detector or CalendarDetector()
        self.task_detector = task_detector or TaskDetector()
        self.reminder_detector = reminder_detector or ReminderDetector()
        self.gmail_detector = gmail_detector or GmailDetector()
        self.rag_enricher = rag_enricher or ProactiveRAGEnricher()
        self.decision_engine = decision_engine or ProactiveDecisionEngine()
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "ProactiveMonitorService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_or_create_preferences(self, db: AsyncSession, user_id: str) -> UserPreference:
        """Retrieves or initializes privacy-conscious default preferences for user."""
        stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        res = await db.execute(stmt)
        pref = res.scalar_one_or_none()
        if not pref:
            pref = UserPreference(
                user_id=user_id,
                proactive_enabled=False,  # Privacy-first opt-in default
                calendar_alerts_enabled=True,
                task_alerts_enabled=True,
                reminder_alerts_enabled=True,
                email_alerts_enabled=True,
                quiet_hours_enabled=True,
                quiet_hours_start="22:00",
                quiet_hours_end="08:00",
                defer_high_priority_in_quiet_hours=True,
                user_timezone="UTC",
                min_priority="low",
                max_proactive_per_day=15,
                cooldown_minutes=60,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(pref)
            await db.commit()
            await db.refresh(pref)
        return pref

    async def evaluate_user_proactive(
        self,
        db: AsyncSession,
        user_id: str,
        now_utc: Optional[datetime] = None,
        global_llm_budget_remaining: int = MAX_LLM_CALLS_PER_GLOBAL_CYCLE,
    ) -> Dict[str, Any]:
        """
        Executes all active detectors for a single user, passes candidates through the decision
        engine, creates notifications, and safely updates checkpoints.
        """
        now = now_utc or datetime.now(timezone.utc)
        pref = await self.get_or_create_preferences(db, user_id)

        stats = {
            "user_id": user_id,
            "proactive_enabled": pref.proactive_enabled,
            "candidates_detected": 0,
            "notifications_created": 0,
            "notifications_deferred": 0,
            "notifications_suppressed": 0,
            "llm_calls_used": 0,
        }

        # If user has not enabled proactive assistant, skip detection immediately
        if not pref.proactive_enabled:
            return stats

        all_candidates: List[dict] = []

        # 1. Calendar Detector
        if pref.calendar_alerts_enabled:
            try:
                cal_candidates = await self.calendar_detector.detect_events(db, user_id, now)
                all_candidates.extend(cal_candidates)
            except Exception as exc:
                logger.warning(f"Calendar detector error for user={user_id[:8]}: {exc}")

        # 2. Task Detector
        if pref.task_alerts_enabled:
            try:
                task_candidates = await self.task_detector.detect_tasks(db, user_id, now)
                all_candidates.extend(task_candidates)
            except Exception as exc:
                logger.warning(f"Task detector error for user={user_id[:8]}: {exc}")

        # 3. Reminder Detector
        if pref.reminder_alerts_enabled:
            try:
                rem_candidates = await self.reminder_detector.detect_reminders(db, user_id, now)
                all_candidates.extend(rem_candidates)
            except Exception as exc:
                logger.warning(f"Reminder detector error for user={user_id[:8]}: {exc}")

        # 4. Gmail Detector (Incremental with checkpoint)
        if pref.email_alerts_enabled:
            try:
                gmail_candidates, new_checkpoint = await self.gmail_detector.detect_emails(db, user_id, pref, now)
                all_candidates.extend(gmail_candidates)
                if new_checkpoint is not None:
                    pref.last_gmail_proactive_check_at = new_checkpoint
                    await db.commit()
            except Exception as exc:
                logger.warning(f"Gmail detector error for user={user_id[:8]}: {exc}")

        stats["candidates_detected"] = len(all_candidates)

        # 5. Evaluate each candidate through Decision Engine
        user_llm_calls = 0
        for cand in all_candidates:
            # 5a. Optional RAG context enrichment for high-priority meetings/tasks
            if cand.get("priority") in ["high", "urgent"] and cand.get("source_type") in ["calendar", "gmail"]:
                enrichment = await self.rag_enricher.enrich_candidate(db, user_id, cand.get("title", ""))
                if enrichment:
                    cand["citations"] = enrichment.get("citations", [])
                    cand["metadata_json"]["rag_context"] = enrichment.get("formatted_context", "")

            # 5b. Check LLM budget
            can_use_llm = (
                user_llm_calls < MAX_LLM_CALLS_PER_USER_CYCLE
                and (global_llm_budget_remaining - stats["llm_calls_used"]) > 0
            )

            should_deliver, reason, enriched_cand, used_llm = await self.decision_engine.evaluate_candidate(
                db=db,
                user_pref=pref,
                candidate=cand,
                now_utc=now,
                can_use_llm=can_use_llm,
            )

            if used_llm:
                user_llm_calls += 1
                stats["llm_calls_used"] += 1

            if should_deliver and enriched_cand:
                # 5c. Deliver In-App Notification
                suggested_act_dict = (
                    enriched_cand["suggested_action"].model_dump()
                    if enriched_cand.get("suggested_action")
                    else None
                )
                meta_payload = enriched_cand.get("metadata_json", {})
                if suggested_act_dict:
                    meta_payload["suggested_action"] = suggested_act_dict
                if enriched_cand.get("citations"):
                    meta_payload["citations"] = enriched_cand["citations"]

                created_notif = await NotificationService.create_notification(
                    db=db,
                    user_id=user_id,
                    idempotency_key=enriched_cand["idempotency_key"],
                    title=enriched_cand["title"],
                    message=enriched_cand["message"],
                    notification_type=enriched_cand["detection_type"],
                    priority=enriched_cand["priority"],
                    source_type=enriched_cand["source_type"],
                    source_id=enriched_cand.get("source_id"),
                    metadata_json=meta_payload,
                )
                if created_notif:
                    stats["notifications_created"] += 1
            elif reason == "deferred_quiet_hours":
                stats["notifications_deferred"] += 1
            else:
                stats["notifications_suppressed"] += 1

        return stats

    async def run_proactive_cycle(self) -> Dict[str, Any]:
        """
        Main scheduler task loop.
        Acquires concurrency lock and processes all active users within hard timeouts and budgets.
        Supports PostgreSQL distributed advisory locks for multi-worker safety.
        """
        async with self._lock:
            start_time = datetime.now(timezone.utc)
            global_stats = {
                "started_at": start_time.isoformat(),
                "users_processed": 0,
                "total_notifications_created": 0,
                "global_llm_calls_used": 0,
                "errors": 0,
            }

            async with AsyncSessionLocal() as lock_session:
                is_pg = lock_session.bind and lock_session.bind.dialect.name == "postgresql"
                acquired_dist_lock = False
                if is_pg:
                    try:
                        res = await lock_session.execute(
                            text("SELECT pg_try_advisory_lock(:lock_id)"),
                            {"lock_id": PROACTIVE_ADVISORY_LOCK_ID},
                        )
                        acquired_dist_lock = bool(res.scalar())
                        if not acquired_dist_lock:
                            logger.info("Proactive cycle already running in another worker process, skipping cycle.")
                            global_stats["skipped_due_to_lock"] = True
                            return global_stats
                    except Exception as e:
                        logger.warning(f"Could not check advisory lock: {e}")

                try:
                    # Fetch all active users
                    stmt = select(User.id).where(User.is_active.is_(True))
                    res = await lock_session.execute(stmt)
                    active_user_ids = list(res.scalars().all())

                    for user_id in active_user_ids:
                        try:
                            async with AsyncSessionLocal() as user_session:
                                remaining_budget = MAX_LLM_CALLS_PER_GLOBAL_CYCLE - global_stats["global_llm_calls_used"]
                                user_task = self.evaluate_user_proactive(
                                    db=user_session,
                                    user_id=user_id,
                                    now_utc=start_time,
                                    global_llm_budget_remaining=max(0, remaining_budget),
                                    )
                                u_stat = await asyncio.wait_for(user_task, timeout=PROACTIVE_EVALUATION_TIMEOUT_SECONDS)
                                global_stats["users_processed"] += 1
                                global_stats["total_notifications_created"] += u_stat.get("notifications_created", 0)
                                global_stats["global_llm_calls_used"] += u_stat.get("llm_calls_used", 0)
                        except Exception as exc:
                            global_stats["errors"] += 1
                            logger.exception(f"Proactive cycle failure for user={user_id[:8]}: {exc}")

                    return global_stats
                finally:
                    if is_pg and acquired_dist_lock:
                        try:
                            await lock_session.execute(
                                text("SELECT pg_advisory_unlock(:lock_id)"),
                                {"lock_id": PROACTIVE_ADVISORY_LOCK_ID},
                            )
                            await lock_session.commit()
                        except Exception as e:
                            logger.warning(f"Error releasing advisory lock: {e}")

