"""
Proactive Decision Engine (Milestone 8).
Executes quiet hours, user preference checks, daily rate limiting, cooldown filtering,
static SuggestedAction risk resolution, and bounded LLM summarization.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
import zoneinfo
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preference import UserPreference
from app.models.notification import Notification
from app.schemas.proactive import SuggestedAction
from app.ai.agent.tool_registry import RiskLevel
from app.ai.providers.base import LLMProvider, LLMMessage
from app.ai.providers.gemini_provider import GeminiProvider

logger = logging.getLogger(__name__)

PRIORITY_RANKS = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "urgent": 4,
}

# Static allowlist mapping action_type to server-authoritative RiskLevel
STATIC_ACTION_RISK_MAP = {
    "view_event": RiskLevel.READ,
    "get_task": RiskLevel.READ,
    "list_tasks": RiskLevel.READ,
    "get_reminder": RiskLevel.READ,
    "list_reminders": RiskLevel.READ,
    "create_task": RiskLevel.LOW_RISK_WRITE,
    "complete_task": RiskLevel.LOW_RISK_WRITE,
    "reschedule_task": RiskLevel.LOW_RISK_WRITE,
    "snooze_reminder": RiskLevel.LOW_RISK_WRITE,
    "delete_task": RiskLevel.HIGH_RISK_WRITE,
    "delete_reminder": RiskLevel.HIGH_RISK_WRITE,
    "cancel_reminder": RiskLevel.HIGH_RISK_WRITE,
}


def is_in_quiet_hours(
    pref: UserPreference,
    now_utc: Optional[datetime] = None,
) -> bool:
    """
    Evaluates whether the given UTC timestamp falls inside the user's localized quiet hours window.
    Handles timezone conversions, DST shifts, and midnight rollover (e.g., 22:00 -> 08:00).
    """
    if not pref.quiet_hours_enabled:
        return False

    now = now_utc or datetime.now(timezone.utc)
    try:
        user_tz = zoneinfo.ZoneInfo(pref.user_timezone)
        local_now = now.astimezone(user_tz)
    except Exception:
        local_now = now.astimezone(timezone.utc)

    start_parts = pref.quiet_hours_start.split(":")
    end_parts = pref.quiet_hours_end.split(":")
    start_hour, start_min = int(start_parts[0]), int(start_parts[1])
    end_hour, end_min = int(end_parts[0]), int(end_parts[1])

    current_minutes = local_now.hour * 60 + local_now.minute
    start_minutes = start_hour * 60 + start_min
    end_minutes = end_hour * 60 + end_min

    if start_minutes < end_minutes:
        # Standard window within same day (e.g. 01:00 to 06:00)
        return start_minutes <= current_minutes < end_minutes
    else:
        # Midnight rollover window (e.g. 22:00 to 08:00)
        return current_minutes >= start_minutes or current_minutes < end_minutes


def build_user_scoped_idempotency_key(
    user_id: str,
    source_type: str,
    detection_type: str,
    source_id: Optional[str],
    anchor: str,
) -> str:
    """Generates the canonical user-scoped idempotency key."""
    clean_src = (source_id or "generic").replace(":", "_")
    clean_anchor = anchor.replace(":", "_")
    return f"proactive:{user_id}:{source_type}:{detection_type}:{clean_src}:{clean_anchor}"


class ProactiveDecisionEngine:
    """
    Orchestrates filtering, scoring, quiet-hours suppression, and safe delivery decisions.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider

    def resolve_action_risk(self, action: Optional[SuggestedAction]) -> Optional[SuggestedAction]:
        """
        Enforces static backend risk level allowlist on SuggestedAction.
        Client or LLM-specified risk levels are discarded.
        """
        if not action:
            return None

        # Resolve strictly from static allowlist
        authoritative_risk = STATIC_ACTION_RISK_MAP.get(action.action_type, RiskLevel.HIGH_RISK_WRITE)
        action.risk_level = authoritative_risk
        return action

    async def evaluate_candidate(
        self,
        db: AsyncSession,
        user_pref: UserPreference,
        candidate: dict,
        now_utc: Optional[datetime] = None,
        can_use_llm: bool = True,
    ) -> Tuple[bool, str, Optional[dict], bool]:
        """
        Evaluates a candidate alert against all decision rules.
        Returns: (should_deliver, reason, enriched_candidate_or_none, used_llm_flag)
        """
        now = now_utc or datetime.now(timezone.utc)
        user_id = user_pref.user_id

        # 1. Master Toggle Check
        if not user_pref.proactive_enabled:
            return False, "proactive_disabled", None, False

        # 2. Category Toggle Check
        source_type = candidate.get("source_type", "system")
        if source_type == "calendar" and not user_pref.calendar_alerts_enabled:
            return False, "calendar_alerts_disabled", None, False
        if source_type == "task" and not user_pref.task_alerts_enabled:
            return False, "task_alerts_disabled", None, False
        if source_type == "reminder" and not user_pref.reminder_alerts_enabled:
            return False, "reminder_alerts_disabled", None, False
        if source_type == "gmail" and not user_pref.email_alerts_enabled:
            return False, "email_alerts_disabled", None, False

        # 3. Priority Threshold Check
        candidate_priority = candidate.get("priority", "medium").lower()
        min_rank = PRIORITY_RANKS.get(user_pref.min_priority.lower(), 1)
        cand_rank = PRIORITY_RANKS.get(candidate_priority, 2)
        if cand_rank < min_rank:
            return False, f"below_min_priority_{user_pref.min_priority}", None, False

        # 4. Quiet Hours Check
        in_quiet = is_in_quiet_hours(user_pref, now)
        if in_quiet:
            if candidate_priority == "urgent":
                # Urgent alerts always bypass quiet hours
                pass
            elif candidate_priority == "high" and not user_pref.defer_high_priority_in_quiet_hours:
                # User specifically allowed high priority in quiet hours
                pass
            else:
                return False, "deferred_quiet_hours", None, False

        # 5. Cooldown Check (same source_id within cooldown_minutes)
        source_id = candidate.get("source_id")
        cooldown_mins = user_pref.cooldown_minutes if user_pref.cooldown_minutes is not None else 60
        if source_id and cooldown_mins > 0:
            cooldown_cutoff = now - timedelta(minutes=cooldown_mins)
            stmt_cooldown = (
                select(func.count(Notification.id))
                .where(
                    and_(
                        Notification.user_id == user_id,
                        Notification.source_type == source_type,
                        Notification.source_id == source_id,
                        Notification.created_at >= cooldown_cutoff,
                    )
                )
            )
            count_recent = (await db.execute(stmt_cooldown)).scalar_one() or 0
            if count_recent > 0:
                return False, "cooldown_suppressed", None, False

        # 6. Daily Quota Check
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        stmt_daily = (
            select(func.count(Notification.id))
            .where(
                and_(
                    Notification.user_id == user_id,
                    Notification.notification_type != "reminder",  # M5 reminders don't count toward proactive quota
                    Notification.created_at >= start_of_day,
                )
            )
        )
        daily_count = (await db.execute(stmt_daily)).scalar_one() or 0
        max_daily = user_pref.max_proactive_per_day if user_pref.max_proactive_per_day is not None else 15
        if daily_count >= max_daily:
            return False, "daily_quota_exceeded", None, False

        # 7. Generate User-Scoped Idempotency Key
        idempotency_key = build_user_scoped_idempotency_key(
            user_id=user_id,
            source_type=source_type,
            detection_type=candidate.get("detection_type", "alert"),
            source_id=source_id,
            anchor=candidate.get("idempotency_anchor", "now"),
        )
        candidate["idempotency_key"] = idempotency_key

        # 8. Check Existing Idempotency in Database
        stmt_idem = select(Notification.id).where(
            and_(
                Notification.user_id == user_id,
                Notification.idempotency_key == idempotency_key,
            )
        )
        existing_notif = (await db.execute(stmt_idem)).scalar_one_or_none()
        if existing_notif is not None:
            return False, "already_notified", None, False

        # 9. Resolve static risk level for SuggestedAction
        if candidate.get("suggested_action"):
            candidate["suggested_action"] = self.resolve_action_risk(candidate["suggested_action"])

        # 10. Optional Bounded LLM Summarization (Cost-controlled)
        used_llm = False
        if can_use_llm and candidate.get("metadata_json", {}).get("needs_llm_summary") and self.llm_provider:
            try:
                summary_prompt = (
                    f"Summarize this personal event into a concise 1-sentence notification.\n"
                    f"Title: {candidate.get('title')}\n"
                    f"Details: {candidate.get('message')}\n"
                    f"Do not invent facts or external citations."
                )
                messages = [LLMMessage(role="user", content=summary_prompt)]
                llm_task = self.llm_provider.generate_response(messages=messages, timeout=10.0)
                resp = await asyncio.wait_for(llm_task, timeout=10.0)
                if resp and resp.content:
                    candidate["message"] = resp.content.strip()
                    used_llm = True
            except Exception as exc:
                logger.info(f"LLM summarization skipped/failed ({exc}). Used deterministic message.")

        return True, "approved", candidate, used_llm
