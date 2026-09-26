"""
Comprehensive Regression Tests for Time-Aware Gmail Interview Query Logic.
Validates:
- Case A: Current time = Sep 24, 2026 02:00 IST, Interview = Sep 23, 2026 18:00 IST -> EXCLUDE as past.
- Case B: Current time = Sep 24, 2026 02:00 IST, Interview = Sep 24, 2026 18:00 IST -> INCLUDE as upcoming.
- Case C: User asks "interviews after 6 PM", Interview = Sep 24, 17:00 -> EXCLUDE.
- Case D: User asks "interviews after 6 PM", Interview = Sep 24, 19:00 -> INCLUDE.
- Case E: Email says "Book your interview slot", no interview time has happened yet -> INCLUDE as pending action.
- Case F: Email says "Your interview was yesterday" -> EXCLUDE.
- Case G: Old interview email exists but a newer email reschedules to tomorrow -> Resolves to the future schedule.
- Timezone-aware datetime handling (UTC vs IST +05:30 vs other offsets).
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.interview_classifier import (
    classify_interview_email,
    filter_interviews,
    parse_temporal_cutoff,
    InterviewStatus,
)
from app.ai.tools.gmail_tools import execute_search_gmail, execute_get_gmail_message
from app.models.user import User


IST = timezone(timedelta(hours=5, minutes=30))


def test_case_a_past_interview_excluded():
    """
    Test Case A:
    Current time = Sep 24, 2026 02:00 IST
    Interview = Sep 23, 2026 18:00 IST
    Result -> EXCLUDED as EXPIRED_PAST.
    """
    now_ist = datetime(2026, 9, 24, 2, 0, 0, tzinfo=IST)
    now_utc = now_ist.astimezone(timezone.utc)

    # Email received on Sep 23 referencing interview at Sep 23 at 6 PM
    email_recv_dt = datetime(2026, 9, 23, 17, 30, 0, tzinfo=IST)
    res = classify_interview_email(
        subject="Interview Scheduled: Frontend Engineer",
        body_or_snippet="Your interview is scheduled for 23rd September at 6 pm on Zoom.",
        email_received_dt=email_recv_dt,
        reference_cutoff=now_utc,
        now_ref=now_utc,
    )

    assert res["status"] == InterviewStatus.EXPIRED_PAST
    assert res["is_pending_or_upcoming"] is False


def test_case_b_future_interview_included():
    """
    Test Case B:
    Current time = Sep 24, 2026 02:00 IST
    Interview = Sep 24, 2026 18:00 IST (later today)
    Result -> INCLUDED as UPCOMING.
    """
    now_ist = datetime(2026, 9, 24, 2, 0, 0, tzinfo=IST)
    now_utc = now_ist.astimezone(timezone.utc)

    email_recv_dt = datetime(2026, 9, 23, 20, 0, 0, tzinfo=IST)
    res = classify_interview_email(
        subject="Interview Scheduled: Senior AI Developer",
        body_or_snippet="Your technical interview is scheduled for 24th September at 6 pm on Google Meet.",
        email_received_dt=email_recv_dt,
        reference_cutoff=now_utc,
        now_ref=now_utc,
    )

    assert res["status"] == InterviewStatus.UPCOMING
    assert res["is_pending_or_upcoming"] is True
    assert res["scheduled_time"] is not None


def test_case_c_user_asks_after_6pm_and_interview_is_5pm_excluded():
    """
    Test Case C:
    User asks "interviews after 6 PM"
    Interview = Sep 24, 17:00 (5 PM)
    Result -> EXCLUDED (17:00 <= 18:00 cutoff).
    """
    now_ist = datetime(2026, 9, 24, 10, 0, 0, tzinfo=IST)
    cutoff_dt, desc = parse_temporal_cutoff("interviews after 6 PM", now_ist)
    assert cutoff_dt.hour == 18

    res = classify_interview_email(
        subject="Interview Invitation",
        body_or_snippet="Your interview is set for Sep 24 at 5:00 pm.",
        email_received_dt=now_ist,
        reference_cutoff=cutoff_dt,
        now_ref=now_ist,
    )

    assert res["status"] == InterviewStatus.EXPIRED_PAST
    assert res["is_pending_or_upcoming"] is False


def test_case_d_user_asks_after_6pm_and_interview_is_7pm_included():
    """
    Test Case D:
    User asks "interviews after 6 PM"
    Interview = Sep 24, 19:00 (7 PM)
    Result -> INCLUDED (19:00 > 18:00 cutoff).
    """
    now_ist = datetime(2026, 9, 24, 10, 0, 0, tzinfo=IST)
    cutoff_dt, desc = parse_temporal_cutoff("interviews after 6 PM", now_ist)

    res = classify_interview_email(
        subject="Interview Invitation",
        body_or_snippet="Your interview is set for Sep 24 at 7:00 pm.",
        email_received_dt=now_ist,
        reference_cutoff=cutoff_dt,
        now_ref=now_ist,
    )

    assert res["status"] == InterviewStatus.UPCOMING
    assert res["is_pending_or_upcoming"] is True


def test_case_e_pending_booking_action_included():
    """
    Test Case E:
    Email says "Book your interview slot"
    No interview time has happened yet and booking is still open.
    Result -> INCLUDED as PENDING_ACTION.
    """
    now = datetime(2026, 9, 24, 2, 0, 0, tzinfo=timezone.utc)
    email_recv_dt = now - timedelta(days=1)

    res = classify_interview_email(
        subject="Action Required: Book your interview slot with Acme Corp",
        body_or_snippet="Please select your interview slot for the Senior Backend Engineer role at your earliest convenience.",
        email_received_dt=email_recv_dt,
        reference_cutoff=now,
        now_ref=now,
    )

    assert res["status"] == InterviewStatus.PENDING_ACTION
    assert res["is_pending_or_upcoming"] is True


def test_case_f_interview_was_yesterday_excluded():
    """
    Test Case F:
    Email says "Your interview was yesterday" or "Thank you for attending".
    Result -> EXCLUDED as HISTORICAL.
    """
    now = datetime(2026, 9, 24, 2, 0, 0, tzinfo=timezone.utc)

    res = classify_interview_email(
        subject="Interview Feedback",
        body_or_snippet="Thank you for attending the interview yesterday. We will get back to you shortly.",
        email_received_dt=now - timedelta(days=1),
        reference_cutoff=now,
        now_ref=now,
    )

    assert res["status"] == InterviewStatus.HISTORICAL
    assert res["is_pending_or_upcoming"] is False


def test_case_g_rescheduled_interview_resolution():
    """
    Test Case G:
    Old interview email exists for Sep 20, but a newer email reschedules the interview to tomorrow (Sep 25).
    Result -> Returns the newer future schedule.
    """
    now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

    messages = [
        {
            "id": "msg_old",
            "subject": "Interview Scheduled",
            "snippet": "Your interview is on 20 Sept at 10 am.",
            "timestamp": "2026-09-18T10:00:00Z",
        },
        {
            "id": "msg_new",
            "subject": "Interview Rescheduled to tomorrow",
            "snippet": "Your interview has been rescheduled to tomorrow at 4 pm.",
            "timestamp": "2026-09-24T10:00:00Z",
        },
    ]

    filtered = filter_interviews(messages, user_query="Is there any pending interview in my mail?", now_ref=now)

    # Only the rescheduled future interview is retained
    assert len(filtered) == 1
    assert filtered[0]["id"] == "msg_new"
    assert filtered[0]["interview_classification"]["status"] == InterviewStatus.UPCOMING


@pytest.mark.asyncio
async def test_execute_search_gmail_enriches_temporal_classification(test_db: AsyncSession):
    """
    Verifies that execute_search_gmail enriches interview messages with interview_temporal_status
    and is_pending_or_upcoming fields.
    """
    user = User(id="u_test_gmail_temp", email="tester@example.com", full_name="Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()

    mock_gmail_svc = AsyncMock()
    mock_resp = MagicMock()

    now_utc = datetime.now(timezone.utc)
    m1 = MagicMock()
    m1.id = "m1"
    m1.subject = "Past Interview"
    m1.sender = "hr@old.com"
    m1.timestamp = (now_utc - timedelta(days=5)).isoformat()
    m1.snippet = "Interview on 20 Sept at 10 am."
    m1.is_unread = False
    m1.has_attachments = False

    m2 = MagicMock()
    m2.id = "m2"
    m2.subject = "Upcoming Technical Interview"
    m2.sender = "hr@new.com"
    m2.timestamp = (now_utc + timedelta(days=1)).isoformat()
    m2.snippet = "Your interview is scheduled for tomorrow at 4 pm."
    m2.is_unread = True
    m2.has_attachments = False

    mock_resp.messages = [m1, m2]
    mock_gmail_svc.list_messages.return_value = mock_resp

    with patch("app.ai.tools.gmail_tools.GmailService", return_value=mock_gmail_svc):
        res = await execute_search_gmail(user_id=user.id, db=test_db, query="interview")

        assert res["status"] == "success"
        msgs = res["messages"]
        assert len(msgs) == 2

        # m1 is past
        assert msgs[0]["interview_temporal_status"] == "EXPIRED_PAST"
        assert msgs[0]["is_pending_or_upcoming"] is False

        # m2 is upcoming
        assert msgs[1]["interview_temporal_status"] == "UPCOMING"
        assert msgs[1]["is_pending_or_upcoming"] is True
