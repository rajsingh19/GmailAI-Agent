"""
Gmail Detector for Proactive AI Assistant (Milestone 8).
Executes bounded incremental scanning of unread messages and recent inbox items using state checkpointing.
Never persists sensitive email bodies for checkpointing.
Treats all email content as UNTRUSTED DATA.
"""
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.proactive import SuggestedAction
from app.ai.agent.tool_registry import RiskLevel
from app.services.gmail_service import GmailService
from app.models.user_preference import UserPreference
from app.services.proactive.detectors.datetime_extractor import extract_datetime_from_text

logger = logging.getLogger(__name__)

ACTIONABLE_KEYWORDS = [
    r"\bdeadline\b",
    r"\burgent\b",
    r"\baction\s+required\b",
    r"\breview\s+by\b",
    r"\bplease\s+reply\b",
    r"\basap\b",
    r"\bmeeting\s+request\b",
    r"\bmeeting\s+invitation\b",
    r"\bby\s+(today|tomorrow|monday|tuesday|wednesday|thursday|friday|eod)\b",
    r"\bimportant\b",
    r"\binterview(\s+(call|round|discussion|scheduled|invitation|invite))?\b",
    r"\btechnical\s+round\b",
    r"\bscreening\s+call\b",
    r"\b(assessment|shortlisted)\b",
    r"\brsvp\b",
    r"\b(invite|invitation)\b",
    r"\b(calendar\.app\.google|meet\.google\.com|zoom\.us)\b",
]
ACTION_REGEX = re.compile("|".join(ACTIONABLE_KEYWORDS), re.IGNORECASE)

INTERVIEW_KEYWORDS = [
    r"\binterview(\s+(call|round|discussion|scheduled|invitation|invite))?\b",
    r"\btechnical\s+round\b",
    r"\bscreening\s+call\b",
    r"\b(assessment|shortlisted)\b",
    r"\bmeeting\s+invitation\b",
    r"\brsvp\b",
    r"\b(calendar\.app\.google|meet\.google\.com|zoom\.us)\b",
]
INTERVIEW_REGEX = re.compile("|".join(INTERVIEW_KEYWORDS), re.IGNORECASE)


class GmailDetector:
    """
    Evaluates recent unread and recent inbox inbound emails for actionable requests, deadlines,
    and interview/meeting scheduling opportunities.
    """

    def __init__(self, gmail_service: Optional[Any] = None):
        self.gmail_service = gmail_service

    async def detect_emails(
        self,
        db: AsyncSession,
        user_id: str,
        user_pref: Optional[UserPreference] = None,
        now_utc: Optional[datetime] = None,
    ) -> Tuple[List[dict], Optional[datetime]]:
        """
        Scans bounded messages (<=10 fetched, <=5 analyzed).
        Returns (candidates, new_checkpoint_dt_or_none).
        Checkpoint is only advanced if the batch evaluation completed successfully.
        """
        candidates: List[dict] = []
        now = now_utc or datetime.now(timezone.utc)
        last_check = user_pref.last_gmail_proactive_check_at if user_pref else None

        # 1. Build bounded query: includes unread and recent inbox items bounded by checkpoint
        if last_check:
            epoch_sec = int(last_check.timestamp())
            query = f"(is:unread OR label:INBOX) after:{epoch_sec}"
        else:
            query = "(is:unread OR label:INBOX) newer_than:2d"

        gmail_svc = self.gmail_service or GmailService(user_id=user_id, db=db)

        try:
            # Fetch message list (strictly <= 10 items)
            if hasattr(gmail_svc, "list_messages"):
                try:
                    list_res = await gmail_svc.list_messages(
                        db=db,
                        user_id=user_id,
                        q=query,
                        max_results=10,
                        include_spam_trash=False,
                    )
                except TypeError:
                    list_res = await gmail_svc.list_messages(
                        query=query,
                        max_results=10,
                    )
            else:
                list_res = {}
        except Exception as exc:
            logger.warning(f"GmailDetector failed to fetch message list for user={user_id[:8]}: {exc}")
            # Failure -> do not advance checkpoint
            return candidates, None

        if hasattr(list_res, "messages"):
            messages_meta = [{"id": m.id, "thread_id": m.thread_id} for m in list_res.messages]
        elif isinstance(list_res, dict):
            messages_meta = list_res.get("messages", [])
        else:
            messages_meta = []

        # Bounded fallback: if query returned nothing and last_check is set, check recent 2-day inbox
        if not messages_meta and last_check:
            try:
                fallback_query = "label:INBOX newer_than:2d"
                if hasattr(gmail_svc, "list_messages"):
                    try:
                        list_res = await gmail_svc.list_messages(
                            db=db,
                            user_id=user_id,
                            q=fallback_query,
                            max_results=10,
                            include_spam_trash=False,
                        )
                    except TypeError:
                        list_res = await gmail_svc.list_messages(
                            query=fallback_query,
                            max_results=10,
                        )
                if hasattr(list_res, "messages"):
                    messages_meta = [{"id": m.id, "thread_id": m.thread_id} for m in list_res.messages]
                elif isinstance(list_res, dict):
                    messages_meta = list_res.get("messages", [])
            except Exception as fb_exc:
                logger.warning(f"GmailDetector fallback fetch failed: {fb_exc}")

        if not messages_meta:
            # Success with zero new messages -> advance checkpoint to now
            return candidates, now

        # Limit deep inspection to at most 5 messages per cycle to preserve API quota
        messages_to_inspect = messages_meta[:5]
        successful_evaluations = 0

        for msg_item in messages_to_inspect:
            msg_id = msg_item.get("id") if isinstance(msg_item, dict) else getattr(msg_item, "id", None)
            if not msg_id:
                continue

            try:
                try:
                    msg_detail = await gmail_svc.get_message(
                        db=db,
                        user_id=user_id,
                        message_id=msg_id,
                        format_type="full",
                    )
                except TypeError:
                    msg_detail = await gmail_svc.get_message(
                        message_id=msg_id,
                    )
                successful_evaluations += 1
            except Exception as exc:
                logger.warning(f"GmailDetector failed to fetch message {msg_id} for user={user_id[:8]}: {exc}")
                continue

            # Extract subject, sender, and snippet
            if isinstance(msg_detail, dict):
                subject = msg_detail.get("subject") or "No Subject"
                sender = msg_detail.get("from") or "Unknown Sender"
                snippet = msg_detail.get("snippet") or ""
                internal_date_ms = msg_detail.get("internal_date")
            else:
                subject = getattr(msg_detail, "subject", "No Subject")
                sender = getattr(msg_detail, "sender", getattr(msg_detail, "from_header", "Unknown Sender"))
                snippet = getattr(msg_detail, "snippet", "")
                internal_date_ms = getattr(msg_detail, "internal_date", None)

            # Parse message timestamp
            msg_date_dt = now
            if internal_date_ms:
                try:
                    msg_date_dt = datetime.fromtimestamp(int(internal_date_ms) / 1000.0, tz=timezone.utc)
                except Exception:
                    pass

            # Detection check: Actionable Keywords, Interview Signals, or Direct Questions
            combined_text = f"{subject} {snippet}"
            has_action_keyword = bool(ACTION_REGEX.search(combined_text))
            has_interview_signal = bool(INTERVIEW_REGEX.search(combined_text))
            has_question = "?" in snippet

            if has_action_keyword or has_interview_signal or has_question:
                clean_snippet = snippet[:150] + ("..." if len(snippet) > 150 else "")
                
                # Deterministic date/time extraction from text
                event_start, event_end, due_dt = extract_datetime_from_text(combined_text, msg_date_dt)

                action_payload: Dict[str, Any] = {
                    "title": f"Interview: {subject[:50]}" if has_interview_signal else f"Follow up on: {subject[:50]}",
                    "description": f"From: {sender}\nSnippet: {clean_snippet}\nGmail ID: {msg_id}",
                    "priority": "high" if (has_action_keyword or has_interview_signal) else "medium",
                    "source": "gmail",
                    "message_id": msg_id,
                }
                if due_dt:
                    action_payload["due_at"] = due_dt.isoformat()
                if event_start:
                    action_payload["event_start"] = event_start.isoformat()
                if event_end:
                    action_payload["event_end"] = event_end.isoformat()

                is_urgent = has_interview_signal or has_action_keyword
                title_label = f"Interview Call: '{subject[:40]}'" if has_interview_signal else f"Actionable Email: '{subject[:40]}'"
                display_btn = "Create Task for Interview" if has_interview_signal else "Create Task from Email"

                candidates.append({
                    "detection_type": "email_actionable",
                    "source_type": "gmail",
                    "source_id": msg_id,
                    "title": title_label,
                    "message": f"From {sender}: \"{clean_snippet}\". May require your attention or a task follow-up.",
                    "priority": "high" if is_urgent else "medium",
                    "idempotency_anchor": msg_id,
                    "suggested_action": SuggestedAction(
                        action_type="create_task",
                        target_resource="task",
                        target_id=None,
                        risk_level=RiskLevel.LOW_RISK_WRITE,
                        display_label=display_btn,
                        action_payload=action_payload,
                    ),
                    "metadata_json": {
                        "message_id": msg_id,
                        "subject": subject,
                        "sender": sender,
                        "snippet": clean_snippet,
                        "received_at": msg_date_dt.isoformat(),
                        "due_at": due_dt.isoformat() if due_dt else None,
                        "event_start": event_start.isoformat() if event_start else None,
                        "event_end": event_end.isoformat() if event_end else None,
                    },
                })

        # Advance checkpoint only if at least one message was successfully evaluated or list was empty
        new_checkpoint = now if successful_evaluations > 0 else None
        return candidates, new_checkpoint
