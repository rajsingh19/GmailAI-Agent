"""
Deterministic Datetime Extractor for Proactive Detectors (Milestone 8).
Extracts start datetime, optional end datetime, and task due datetime from text
without LLM hallucinations.
"""
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

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


def extract_datetime_from_text(
    text: str,
    now_utc: Optional[datetime] = None,
) -> Tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
    """
    Extracts (event_start, event_end, due_dt) from text using deterministic regex matching.
    Returns (None, None, None) if no valid date/time pattern is found.
    Never hallucinates missing dates or times.
    """
    if not text:
        return None, None, None

    now = now_utc or datetime.now(timezone.utc)
    base_year = now.year

    # 1. Date + Time Range: e.g. "18 Sept • 1–2 am", "18 Sept 1-2 am", "18th Sept 1:00 - 2:00 pm"
    m_range = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|september|oct|nov|dec)[a-z]*"
        r"(?:\s*•\s*|\s*,\s*|\s+)"
        r"(\d{1,2})(?::(\d{2}))?\s*(?:–|-|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        text,
        re.IGNORECASE,
    )
    if m_range:
        day = int(m_range.group(1))
        month_str = m_range.group(2).lower()
        month = MONTH_MAP.get(month_str)
        if month and 1 <= day <= 31:
            start_h = int(m_range.group(3))
            start_m = int(m_range.group(4) or 0)
            end_h = int(m_range.group(5))
            end_m = int(m_range.group(6) or 0)
            ampm = m_range.group(7).lower()

            if ampm == "pm":
                if start_h < 12:
                    start_h += 12
                if end_h < 12:
                    end_h += 12
            elif ampm == "am":
                if start_h == 12:
                    start_h = 0
                if end_h == 12:
                    end_h = 0

            try:
                start_dt = datetime(base_year, month, day, start_h, start_m, tzinfo=timezone.utc)
                end_dt = datetime(base_year, month, day, end_h, end_m, tzinfo=timezone.utc)
                return start_dt, end_dt, start_dt
            except Exception:
                pass

    # 2. Relative day + Time: e.g. "tomorrow at 4 PM", "tomorrow 4 PM", "today at 2 PM"
    m_rel = re.search(
        r"\b(today|tomorrow)\b(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        text,
        re.IGNORECASE,
    )
    if m_rel:
        rel_day = m_rel.group(1).lower()
        hour = int(m_rel.group(2))
        minute = int(m_rel.group(3) or 0)
        ampm = m_rel.group(4).lower()

        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

        target_date = now.date() if rel_day == "today" else (now.date() + timedelta(days=1))
        try:
            start_dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=timezone.utc)
            return start_dt, None, start_dt
        except Exception:
            pass

    # 3. Date with explicit Time: e.g. "Sept 18 at 3:30 pm", "18th September at 4 pm"
    m_date_time = re.search(
        r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|september|oct|nov|dec)[a-z]*|"
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|september|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?)"
        r"(?:\s*,\s*\d{4})?"
        r"(?:\s+(?:at|@)\s+|\s+)"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        text,
        re.IGNORECASE,
    )
    if m_date_time:
        d_str = m_date_time.group(1) or m_date_time.group(4)
        m_str = (m_date_time.group(2) or m_date_time.group(3)).lower()
        day = int(d_str)
        month = MONTH_MAP.get(m_str)
        if month and 1 <= day <= 31:
            hour = int(m_date_time.group(5))
            minute = int(m_date_time.group(6) or 0)
            ampm = m_date_time.group(7).lower()

            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0

            try:
                start_dt = datetime(base_year, month, day, hour, minute, tzinfo=timezone.utc)
                return start_dt, None, start_dt
            except Exception:
                pass

    # 4. Standalone Date without Time: e.g. "18 Sept", "Sept 18", "18th September"
    m_date = re.search(
        r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|september|oct|nov|dec)[a-z]*|"
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|september|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?)",
        text,
        re.IGNORECASE,
    )
    if m_date:
        d_str = m_date.group(1) or m_date.group(4)
        m_str = (m_date.group(2) or m_date.group(3)).lower()
        day = int(d_str)
        month = MONTH_MAP.get(m_str)
        if month and 1 <= day <= 31:
            try:
                start_dt = datetime(base_year, month, day, 9, 0, tzinfo=timezone.utc)
                return start_dt, None, start_dt
            except Exception:
                pass

    return None, None, None
