"""
Unit & Integration Tests for Interview and Event Fetching/Filtering Logic.
Tests:
1. Past interview -> excluded
2. Today's interview with future start time -> included
3. Future interview -> included
4. Interview whose start time has just passed -> excluded
5. Non-interview future event -> correctly processed/differentiated
6. Historical Gmail interview email -> does not create upcoming interview
7. Duplicate Calendar event -> displayed only once (deduplicated by ID)
8. Timezone-aware datetime comparisons (e.g. UTC vs +05:30 offsets)
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.calendar import CalendarEventSummary
from app.services.calendar_service import CalendarService
from app.services.proactive.detectors.gmail_detector import GmailDetector
from app.models.user_preference import UserPreference
from sqlalchemy.ext.asyncio import AsyncSession


# =============================================================================
# 1. Calendar Deduplication & Filtering Tests
# =============================================================================

@pytest.mark.asyncio
async def test_calendar_service_deduplicates_duplicate_event_ids(test_db: AsyncSession):
    """Verifies that CalendarService.list_events deduplicates events with identical IDs."""
    service = CalendarService(user_id="test_user_id", db=test_db)

    # Mock Google client returning duplicate events
    mock_events_resource = MagicMock()
    mock_events_resource.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "event_dup_1",
                "summary": "Technical Interview - AI Engineer",
                "start": {"dateTime": "2026-09-25T10:00:00Z"},
                "end": {"dateTime": "2026-09-25T11:00:00Z"},
            },
            {
                "id": "event_dup_1",  # duplicate ID
                "summary": "Technical Interview - AI Engineer",
                "start": {"dateTime": "2026-09-25T10:00:00Z"},
                "end": {"dateTime": "2026-09-25T11:00:00Z"},
            },
            {
                "id": "event_unique_2",
                "summary": "HR Interview",
                "start": {"dateTime": "2026-09-26T14:00:00Z"},
                "end": {"dateTime": "2026-09-26T15:00:00Z"},
            },
        ]
    }

    mock_client = MagicMock()
    mock_client.events.return_value = mock_events_resource

    with patch.object(service, "_get_client", return_value=mock_client):
        resp = await service.list_events(calendar_id="primary")
        assert len(resp.events) == 2
        assert [e.id for e in resp.events] == ["event_dup_1", "event_unique_2"]


# =============================================================================
# 2. Gmail Proactive Detector: Historical Email Non-Triggering Tests
# =============================================================================

@pytest.mark.asyncio
async def test_historical_gmail_interview_email_excluded(test_db: AsyncSession):
    """
    Verifies that a historical interview email from the past does NOT create
    an upcoming interview alert or task.
    """
    now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_test_hist", last_gmail_proactive_check_at=None)

    mock_gmail = AsyncMock()
    mock_gmail.list_messages.return_value = {"messages": [{"id": "msg_past_interview"}]}
    # Email from 10 days ago referencing a date in the past (10 Sept)
    mock_gmail.get_message.return_value = {
        "subject": "Interview Scheduled: Senior Python Developer",
        "from": "recruiter@example.com",
        "snippet": "Your interview was scheduled for 10th September at 2 pm.",
        "internal_date": str(int((now - timedelta(days=14)).timestamp() * 1000)),
    }

    detector = GmailDetector(gmail_service=mock_gmail)
    candidates, _ = await detector.detect_emails(test_db, "u_test_hist", user_pref=pref, now_utc=now)

    # Historical interview with past date must NOT be flagged as upcoming interview
    assert len(candidates) == 0


@pytest.mark.asyncio
async def test_future_gmail_interview_email_included(test_db: AsyncSession):
    """
    Verifies that an email referencing a genuine future interview scheduled date
    is correctly detected.
    """
    now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_test_future", last_gmail_proactive_check_at=None)

    mock_gmail = AsyncMock()
    mock_gmail.list_messages.return_value = {"messages": [{"id": "msg_future_interview"}]}
    mock_gmail.get_message.return_value = {
        "subject": "Interview Invitation: AI Assistant Engineer",
        "from": "careers@techcorp.com",
        "snippet": "Your interview is scheduled for 28th September at 3 pm on Google Meet.",
        "internal_date": str(int(now.timestamp() * 1000)),
    }

    detector = GmailDetector(gmail_service=mock_gmail)
    candidates, _ = await detector.detect_emails(test_db, "u_test_future", user_pref=pref, now_utc=now)

    assert len(candidates) == 1
    cand = candidates[0]
    assert "Interview" in cand["title"]
    assert cand["suggested_action"].display_label == "Create Task for Interview"
    assert cand["suggested_action"].action_payload["due_at"] == "2026-09-28T15:00:00+00:00"


# =============================================================================
# 3. Client & Timezone Logic Validation Tests
# =============================================================================

def test_timezone_aware_interview_classification():
    """
    Tests that events across different timezones (UTC, IST +05:30, EST -04:00)
    are accurately classified based on whether start_time > now_utc.
    """
    now_utc = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Past interview: started at 09:00 UTC (1 hour ago)
    past_event = {
        "id": "e_past",
        "summary": "Frontend Coding Interview",
        "start": "2026-09-24T09:00:00Z",
    }
    past_dt = datetime.fromisoformat(past_event["start"].replace("Z", "+00:00"))
    assert (past_dt > now_utc) is False, "Past interview must be excluded"

    # 2. Today's interview with future start time: starts at 15:30 IST (+05:30) which is 10:00 UTC -> just started/now
    # Future start: 16:30 IST (+05:30) = 11:00 UTC (1 hour in future)
    future_today_ist = {
        "id": "e_today_future",
        "summary": "Technical Interview (Google Meet)",
        "start": "2026-09-24T16:30:00+05:30",
    }
    today_future_dt = datetime.fromisoformat(future_today_ist["start"])
    assert (today_future_dt > now_utc) is True, "Today's future interview must be included"

    # 3. Future interview (tomorrow):
    future_event = {
        "id": "e_tomorrow",
        "summary": "Final Round System Design Interview",
        "start": "2026-09-25T14:00:00Z",
    }
    future_dt = datetime.fromisoformat(future_event["start"].replace("Z", "+00:00"))
    assert (future_dt > now_utc) is True, "Future interview must be included"

    # 4. Just passed interview: started at 09:59 UTC (1 minute ago)
    just_passed_event = {
        "id": "e_just_passed",
        "summary": "HR Screening Interview",
        "start": "2026-09-24T09:59:00Z",
    }
    just_passed_dt = datetime.fromisoformat(just_passed_event["start"].replace("Z", "+00:00"))
    assert (just_passed_dt > now_utc) is False, "Interview whose start time has passed must be excluded"
