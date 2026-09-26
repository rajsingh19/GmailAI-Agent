"""
Time-Aware Gmail Interview Classifier Service.
Extracts interview schedules, booking deadlines, and temporal status from emails
using timezone-aware datetime comparisons without relying on email received time.

Distinguishes:
- UPCOMING: Scheduled interview datetime > reference_cutoff
- PENDING ACTION: Booking/slot/assessment request still valid and unexpired
- EXPIRED/PAST: Scheduled interview or action deadline <= reference_cutoff
- HISTORICAL: Interview already completed or occurred in the past
"""
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

logger = logging.getLogger(__name__)


class InterviewStatus(str, Enum):
    UPCOMING = "UPCOMING"
    PENDING_ACTION = "PENDING_ACTION"
    EXPIRED_PAST = "EXPIRED_PAST"
    HISTORICAL = "HISTORICAL"
    NON_INTERVIEW = "NON_INTERVIEW"


INTERVIEW_SIGNALS = [
    r"\binterview(\s+(call|round|discussion|scheduled|invitation|invite|slot))?\b",
    r"\btechnical\s+(round|interview)\b",
    r"\b(hr|coding|system\s+design|screening)\s+round\b",
    r"\bscreening\s+call\b",
    r"\b(assessment|shortlisted)\b",
    r"\bbook\s+(your\s+)?(interview\s+)?slot\b",
    r"\bselect\s+(your\s+)?(interview\s+)?slot\b",
]
INTERVIEW_SIGNAL_REGEX = re.compile("|".join(INTERVIEW_SIGNALS), re.IGNORECASE)

PAST_INTERVIEW_MARKERS = [
    r"\b(interview\s+was\s+yesterday|was\s+held\s+on|conducted\s+on)\b",
    r"\bthank\s+you\s+for\s+(attending|interviewing|participating)\b",
    r"\binterview\s+feedback\b",
    r"\bcompleted\s+(your\s+)?interview\b",
    r"\b(attended|finished)\s+the\s+interview\b",
]
PAST_MARKER_REGEX = re.compile("|".join(PAST_INTERVIEW_MARKERS), re.IGNORECASE)

ACTION_REQUEST_MARKERS = [
    r"\bbook\s+(your\s+)?(interview\s+)?slot\b",
    r"\bselect\s+(your\s+)?(interview\s+)?slot\b",
    r"\bchoose\s+(your\s+)?(interview\s+)?time\b",
    r"\bcomplete\s+(the\s+|your\s+)?(assessment|test|task)\b",
    r"\brsvp\s+(for\s+|to\s+)?(interview|discussion)?\b",
]
ACTION_MARKER_REGEX = re.compile("|".join(ACTION_REQUEST_MARKERS), re.IGNORECASE)

RESCHEDULE_MARKERS = [
    r"\brescheduled\s+(to|for)\b",
    r"\bnew\s+time\b",
    r"\bupdated\s+(schedule|time|interview)\b",
    r"\bchanged\s+to\b",
]
RESCHEDULE_REGEX = re.compile("|".join(RESCHEDULE_MARKERS), re.IGNORECASE)


def parse_temporal_cutoff(query: str, now_ref: Optional[datetime] = None) -> Tuple[datetime, Optional[str]]:
    """
    Parses a user query to identify explicit temporal cutoffs (e.g., 'after 6 PM', 'after Sep 24', 'tomorrow').
    If no explicit cutoff is found, defaults to now_ref (timezone-aware UTC).
    """
    now = now_ref or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if not query:
        return now, None

    clean_q = query.lower()

    # 1. "after <time>": e.g. "after 6 PM", "after 6:00 pm", "after 18:00", "after 10 PM"
    m_after_time = re.search(r"\bafter\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", clean_q)
    if m_after_time:
        hour = int(m_after_time.group(1))
        minute = int(m_after_time.group(2) or 0)
        ampm = m_after_time.group(3)

        if ampm:
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
        elif hour < 12 and ("pm" in clean_q or hour <= 7):
            # Infer PM for typical business hours like "after 6"
            hour += 12

        # Check if user mentioned "tomorrow" along with time
        target_date = now.date() + timedelta(days=1) if "tomorrow" in clean_q else now.date()
        cutoff = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=now.tzinfo)
        return cutoff, f"after {hour:02d}:{minute:02d}"

    # 2. "after <date>": e.g. "after Sep 24", "after 24th September", "from today"
    m_after_date = re.search(
        r"(?:after|from)\s+(?:(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|september|oct|nov|dec)|"
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|september|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?)\b",
        clean_q,
    )
    if m_after_date:
        d_str = m_after_date.group(1) or m_after_date.group(4)
        m_str = (m_after_date.group(2) or m_after_date.group(3)).lower()
        day = int(d_str)
        month = MONTH_MAP.get(m_str)
        if month:
            cutoff = datetime(now.year, month, day, 0, 0, tzinfo=now.tzinfo)
            return cutoff, f"after {m_str} {day}"

    # 3. "tomorrow"
    if "tomorrow" in clean_q:
        target_date = now.date() + timedelta(days=1)
        cutoff = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=now.tzinfo)
        return cutoff, "tomorrow"

    return now, None


def classify_interview_email(
    subject: str,
    body_or_snippet: str,
    email_received_dt: Optional[datetime],
    reference_cutoff: datetime,
    now_ref: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Classifies an individual email into UPCOMING, PENDING_ACTION, EXPIRED_PAST, or HISTORICAL.
    Never uses email received time as the scheduled interview time.
    """
    now = now_ref or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if reference_cutoff.tzinfo is None:
        reference_cutoff = reference_cutoff.replace(tzinfo=timezone.utc)

    combined_text = f"{subject} {body_or_snippet}"

    # Check if this email is interview-related
    has_interview_signal = bool(INTERVIEW_SIGNAL_REGEX.search(combined_text))
    if not has_interview_signal:
        return {
            "status": InterviewStatus.NON_INTERVIEW,
            "scheduled_time": None,
            "is_pending_or_upcoming": False,
            "summary": "Non-interview email",
        }

    # Check for explicit past markers (e.g. "Your interview was yesterday", "Thank you for attending")
    if PAST_MARKER_REGEX.search(combined_text):
        return {
            "status": InterviewStatus.HISTORICAL,
            "scheduled_time": None,
            "is_pending_or_upcoming": False,
            "summary": "Historical interview already completed or occurred in the past.",
        }

    # Extract date/time from email content
    # Use email_received_dt as the base year/date context if available
    base_dt = email_received_dt or now
    if base_dt.tzinfo is None:
        base_dt = base_dt.replace(tzinfo=timezone.utc)

    from app.services.proactive.detectors.datetime_extractor import extract_datetime_from_text
    event_start, event_end, due_dt = extract_datetime_from_text(combined_text, base_dt)
    target_time = event_start or due_dt

    is_action_request = bool(ACTION_MARKER_REGEX.search(combined_text))

    if target_time:
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)

        if target_time > reference_cutoff:
            status = InterviewStatus.UPCOMING if not is_action_request else InterviewStatus.PENDING_ACTION
            return {
                "status": status,
                "scheduled_time": target_time.isoformat(),
                "is_pending_or_upcoming": True,
                "summary": f"Interview scheduled for {target_time.strftime('%b %d, %Y at %I:%M %p %Z')}",
            }
        else:
            # Interview scheduled time or action deadline has already passed
            return {
                "status": InterviewStatus.EXPIRED_PAST,
                "scheduled_time": target_time.isoformat(),
                "is_pending_or_upcoming": False,
                "summary": f"Interview occurred or expired on {target_time.strftime('%b %d, %Y at %I:%M %p %Z')}",
            }

    # If no explicit future/past date extracted, check if it's an open action request
    if is_action_request:
        # If email is recent (< 14 days old), treat as valid PENDING_ACTION
        age_days = (now - base_dt).total_seconds() / 86400.0
        if age_days <= 14.0:
            return {
                "status": InterviewStatus.PENDING_ACTION,
                "scheduled_time": None,
                "is_pending_or_upcoming": True,
                "summary": "Pending interview action (slot booking / assessment required)",
            }
        else:
            return {
                "status": InterviewStatus.EXPIRED_PAST,
                "scheduled_time": None,
                "is_pending_or_upcoming": False,
                "summary": "Expired interview booking invitation (older than 14 days)",
            }

    # Default fallback for emails without future dates
    age_days = (now - base_dt).total_seconds() / 86400.0
    if age_days > 7.0:
        return {
            "status": InterviewStatus.HISTORICAL,
            "scheduled_time": None,
            "is_pending_or_upcoming": False,
            "summary": "Old historical interview email with no upcoming schedule",
        }

    return {
        "status": InterviewStatus.HISTORICAL,
        "scheduled_time": None,
        "is_pending_or_upcoming": False,
        "summary": "Interview record without future scheduled time",
    }


def filter_interviews(
    messages: List[Dict[str, Any]],
    user_query: str = "",
    now_ref: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Filters and ranks a list of Gmail messages, returning only genuinely upcoming or pending interviews
    relative to the user's temporal query reference. Handles rescheduling updates.
    """
    now = now_ref or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    cutoff_dt, cutoff_desc = parse_temporal_cutoff(user_query, now)

    results: List[Dict[str, Any]] = []

    for msg in messages:
        subject = msg.get("subject", "")
        snippet = msg.get("snippet", "")
        body = msg.get("body", "")
        combined = f"{snippet} {body}"

        # Parse timestamp from email metadata
        raw_ts = msg.get("timestamp") or msg.get("internal_date")
        msg_dt = None
        if raw_ts:
            try:
                if isinstance(raw_ts, (int, float)) or (isinstance(raw_ts, str) and raw_ts.isdigit()):
                    msg_dt = datetime.fromtimestamp(float(raw_ts) / 1000.0 if float(raw_ts) > 1e11 else float(raw_ts), tz=timezone.utc)
                elif isinstance(raw_ts, str):
                    msg_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except Exception:
                msg_dt = now

        classification = classify_interview_email(
            subject=subject,
            body_or_snippet=combined,
            email_received_dt=msg_dt,
            reference_cutoff=cutoff_dt,
            now_ref=now,
        )

        if classification["is_pending_or_upcoming"]:
            enriched = dict(msg)
            enriched["interview_classification"] = classification
            results.append(enriched)

    return results
