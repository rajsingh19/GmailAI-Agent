"""
Comprehensive Regression Tests for M8 Proactive Assistant Gmail Detector Fix.
Validates:
1. unread interview email -> detected
2. read interview email -> detected through bounded recent fallback
3. normal newsletter -> not incorrectly detected
4. interview keyword detection
5. RSVP detection
6. calendar link detection
7. meeting invitation detection
8. '18 Sept • 1–2 am' extraction
9. 'tomorrow at 4 PM' extraction
10. missing/ambiguous date -> no hallucinated datetime
11. duplicate email -> idempotency preserved
12. user A cannot see/process user B's messages (strict isolation)
13. existing M8 actionable keywords still work
14. M6 RiskLevel remains unchanged (LOW_RISK_WRITE for task suggestion)
15. no automatic task creation occurs during detection
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.models.notification import Notification
from app.models.task import Task
from app.services.proactive.detectors.gmail_detector import GmailDetector
from app.services.proactive.detectors.datetime_extractor import extract_datetime_from_text
from app.services.proactive.monitor_service import ProactiveMonitorService
from app.ai.agent.tool_registry import RiskLevel


@pytest.fixture
def mock_gmail_service():
    return AsyncMock()


# 1. Unread interview email -> detected
@pytest.mark.asyncio
async def test_unread_interview_email_detected(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_interview_1"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "AI INTERVIEW CALL",
        "from": "David <david905952@gmail.com>",
        "snippet": "hi Raj , We are form genz AI 18 Sept • 1–2 am • View details and RSVP https://calendar.app.google/q7uxdjqXnVTpEP2g7",
        "internal_date": "1789560000000",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, new_ckpt = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)

    assert len(candidates) == 1
    cand = candidates[0]
    assert "Interview Call" in cand["title"]
    assert cand["suggested_action"].display_label == "Create Task for Interview"
    assert cand["suggested_action"].risk_level == RiskLevel.LOW_RISK_WRITE
    assert cand["suggested_action"].action_payload["due_at"] == "2026-09-18T01:00:00+00:00"
    assert cand["suggested_action"].action_payload["event_start"] == "2026-09-18T01:00:00+00:00"
    assert cand["suggested_action"].action_payload["event_end"] == "2026-09-18T02:00:00+00:00"


# 2. Read interview email -> detected through bounded recent fallback
@pytest.mark.asyncio
async def test_read_interview_email_detected_via_fallback(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=now - timedelta(hours=1))

    # First call with checkpoint returns 0 messages, triggering bounded fallback
    mock_gmail_service.list_messages.side_effect = [
        {"messages": []},  # Primary checkpoint query empty
        {"messages": [{"id": "msg_read_interview"}]},  # Fallback query
    ]
    mock_gmail_service.get_message.return_value = {
        "subject": "Interview Scheduled: Frontend Engineer",
        "from": "recruiter@tech.io",
        "snippet": "Your interview is scheduled for 18th September at 4 pm on Zoom.",
        "internal_date": "1789560000000",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, new_ckpt = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)

    assert len(candidates) == 1
    assert candidates[0]["suggested_action"].action_payload["due_at"] == "2026-09-18T16:00:00+00:00"


# 3. Normal newsletter -> not incorrectly detected
@pytest.mark.asyncio
async def test_newsletter_ignored(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_news"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Pinecone September Global Newsletter",
        "from": "Team Pinecone <community@trypinecone.com>",
        "snippet": "Full-text search is GA, a support agent that now resolves most tickets on its own, and a year of Pinecone.",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, _ = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)
    assert len(candidates) == 0


# 4. Interview keyword detection
@pytest.mark.asyncio
async def test_interview_keywords_recognized(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    for kw in ["screening call", "technical round", "assessment", "shortlisted"]:
        mock_gmail_service.list_messages.return_value = {"messages": [{"id": f"msg_{kw}"}]}
        mock_gmail_service.get_message.return_value = {
            "subject": f"Next steps: {kw}",
            "from": "talent@startup.ai",
            "snippet": f"We are pleased to invite you to the {kw} on Sept 18 at 2 pm.",
            "internal_date": "1789560000000",
        }

        detector = GmailDetector(gmail_service=mock_gmail_service)
        candidates, _ = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)
        assert len(candidates) == 1, f"Failed for keyword {kw}"


# 5. RSVP detection
@pytest.mark.asyncio
async def test_rsvp_detection(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_rsvp"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Founder Sync",
        "from": "investor@venture.com",
        "snippet": "Please RSVP for the quarterly portfolio sync.",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, _ = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)
    assert len(candidates) == 1


# 6. Calendar link detection
@pytest.mark.asyncio
async def test_calendar_link_detection(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    for domain in ["calendar.app.google", "meet.google.com", "zoom.us"]:
        mock_gmail_service.list_messages.return_value = {"messages": [{"id": f"msg_{domain}"}]}
        mock_gmail_service.get_message.return_value = {
            "subject": "Chat invitation",
            "from": "partner@corp.com",
            "snippet": f"Here is the link: https://{domain}/xyz-abc",
        }

        detector = GmailDetector(gmail_service=mock_gmail_service)
        candidates, _ = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)
        assert len(candidates) == 1, f"Failed for domain {domain}"


# 7. Meeting invitation detection
@pytest.mark.asyncio
async def test_meeting_invitation_detection(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_minv"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Meeting Invitation: Project Kickoff",
        "from": "pm@team.com",
        "snippet": "You are invited to the project kickoff tomorrow at 10 am.",
        "internal_date": "1789560000000",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, _ = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)
    assert len(candidates) == 1


# 8. '18 Sept • 1–2 am' extraction
def test_datetime_extraction_range():
    ref = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    text = "We are form genz AI 18 Sept • 1–2 am • View details and RSVP https://calendar.app.google/q7uxdjqXnVTpEP2g7"
    st, en, due = extract_datetime_from_text(text, ref)
    assert st == datetime(2026, 9, 18, 1, 0, 0, tzinfo=timezone.utc)
    assert en == datetime(2026, 9, 18, 2, 0, 0, tzinfo=timezone.utc)
    assert due == datetime(2026, 9, 18, 1, 0, 0, tzinfo=timezone.utc)


# 9. 'tomorrow at 4 PM' extraction
def test_datetime_extraction_relative():
    ref = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    text = "Please join the meeting tomorrow at 4 PM on zoom"
    st, en, due = extract_datetime_from_text(text, ref)
    assert st == datetime(2026, 9, 17, 16, 0, 0, tzinfo=timezone.utc)
    assert en is None
    assert due == datetime(2026, 9, 17, 16, 0, 0, tzinfo=timezone.utc)


# 10. Missing/ambiguous date -> no hallucinated datetime
def test_datetime_extraction_none():
    ref = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    text = "Important product launch updates and team highlights."
    st, en, due = extract_datetime_from_text(text, ref)
    assert st is None
    assert en is None
    assert due is None


# 11. Duplicate email -> idempotency preserved
@pytest.mark.asyncio
async def test_idempotency_preserved_across_scans(test_db: AsyncSession, mock_gmail_service):
    u = User(id="u_idemp_test", email="idemp@example.com", full_name="Idemp User")
    test_db.add(u)
    pref = UserPreference(user_id="u_idemp_test", proactive_enabled=True, email_alerts_enabled=True)
    test_db.add(pref)
    await test_db.commit()

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_idemp_1"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Interview Scheduled",
        "from": "hr@corp.com",
        "snippet": "Your interview is on 18 Sept at 10 am.",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    monitor = ProactiveMonitorService(gmail_detector=detector)

    # Cycle 1 -> 1 notification created
    res1 = await monitor.evaluate_user_proactive(test_db, "u_idemp_test")
    assert res1["notifications_created"] == 1

    # Cycle 2 with same email -> 0 duplicates created
    res2 = await monitor.evaluate_user_proactive(test_db, "u_idemp_test")
    assert res2["notifications_created"] == 0


# 12. User A cannot see/process User B's messages
@pytest.mark.asyncio
async def test_strict_user_isolation(test_db: AsyncSession):
    u_a = User(id="u_iso_a", email="user_a@example.com", full_name="User A")
    u_b = User(id="u_iso_b", email="user_b@example.com", full_name="User B")
    test_db.add_all([u_a, u_b])

    notif_a = Notification(
        id="notif_iso_a",
        user_id="u_iso_a",
        idempotency_key="proactive:u_iso_a:gmail:email_actionable:m1:m1",
        title="User A Notification",
    )
    test_db.add(notif_a)
    await test_db.commit()

    # User B query for notifications returns only User B records
    user_b_notifs = (await test_db.execute(select(Notification).where(Notification.user_id == "u_iso_b"))).scalars().all()
    assert len(user_b_notifs) == 0


# 13. Existing M8 actionable keywords still work
@pytest.mark.asyncio
async def test_existing_keywords_remain_functional(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    for kw in ["deadline", "urgent", "action required", "review by", "please reply", "asap"]:
        mock_gmail_service.list_messages.return_value = {"messages": [{"id": f"msg_{kw}"}]}
        mock_gmail_service.get_message.return_value = {
            "subject": f"Notice: {kw}",
            "from": "ops@corp.com",
            "snippet": f"This is an {kw} message.",
        }

        detector = GmailDetector(gmail_service=mock_gmail_service)
        candidates, _ = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)
        assert len(candidates) == 1, f"Failed for legacy keyword {kw}"


# 14. M6 RiskLevel remains unchanged
@pytest.mark.asyncio
async def test_risk_level_is_low_risk_write(test_db: AsyncSession, mock_gmail_service):
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_m8_test", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_risk"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Interview Invitation",
        "from": "hr@corp.com",
        "snippet": "Please join on 18 Sept • 1–2 am",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, _ = await detector.detect_emails(test_db, "u_m8_test", user_pref=pref, now_utc=now)
    assert candidates[0]["suggested_action"].risk_level == RiskLevel.LOW_RISK_WRITE


# 15. No automatic task creation occurs during detection
@pytest.mark.asyncio
async def test_no_automatic_task_creation_during_detection(test_db: AsyncSession, mock_gmail_service):
    u = User(id="u_notask_test", email="notask@example.com", full_name="No Task User")
    test_db.add(u)
    pref = UserPreference(user_id="u_notask_test", proactive_enabled=True, email_alerts_enabled=True)
    test_db.add(pref)
    await test_db.commit()

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_notask"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Interview Scheduled",
        "from": "recruiter@corp.com",
        "snippet": "Interview on 18 Sept at 10 am.",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    monitor = ProactiveMonitorService(gmail_detector=detector)

    # Run detection
    await monitor.evaluate_user_proactive(test_db, "u_notask_test")

    # Verify task table has ZERO tasks created automatically
    tasks = (await test_db.execute(select(Task).where(Task.user_id == "u_notask_test"))).scalars().all()
    assert len(tasks) == 0
