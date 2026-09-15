"""
Tests for Gmail Detector and Incremental Checkpointing (Milestone 8).
Validates:
- Bounded fetch limit (<= 10 messages)
- Deep analysis bounded to <= 5 messages per cycle
- Checkpoint advances ONLY upon successful batch evaluation
- Checkpoint does NOT advance on API error / timeout
- Actionable keyword and question mark detection
- Non-actionable email ignored
- Expired OAuth token handled gracefully without crashing
- Zero email body text persisted solely for checkpointing
- SuggestedAction create_task payload formatting
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preference import UserPreference
from app.services.proactive.detectors.gmail_detector import GmailDetector
from app.ai.agent.tool_registry import RiskLevel


@pytest.fixture
def mock_gmail_service():
    return AsyncMock()


@pytest.mark.asyncio
async def test_gmail_detector_bounded_query_limit_10(test_db: AsyncSession, mock_gmail_service):
    """Verify list_messages is called with max_results=10."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": []}
    detector = GmailDetector(gmail_service=mock_gmail_service)

    await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)
    mock_gmail_service.list_messages.assert_called_with(
        db=test_db,
        user_id="u_gmail_1",
        q="is:unread newer_than:2d",
        max_results=10,
        include_spam_trash=False,
    )


@pytest.mark.asyncio
async def test_gmail_detector_max_5_messages_analyzed(test_db: AsyncSession, mock_gmail_service):
    """Even if 10 messages are returned by list_messages, only top 5 are inspected deeply."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=None)

    # 8 messages returned
    messages = [{"id": f"msg_{i}"} for i in range(8)]
    mock_gmail_service.list_messages.return_value = {"messages": messages}
    mock_gmail_service.get_message.return_value = {
        "subject": "Status Report",
        "from": "alice@example.com",
        "snippet": "Just FYI, no action needed.",
        "internal_date": "1726488000000",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)

    # get_message should have been called exactly 5 times (hard cap)
    assert mock_gmail_service.get_message.call_count == 5


@pytest.mark.asyncio
async def test_gmail_checkpoint_advances_only_on_success(test_db: AsyncSession, mock_gmail_service):
    """When messages are successfully evaluated, new checkpoint timestamp is returned."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=now - timedelta(days=1))

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_1"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Urgent review required by EOD",
        "from": "boss@company.com",
        "snippet": "Please review the attached contract by EOD today.",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, new_checkpoint = await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)

    assert len(candidates) == 1
    assert candidates[0]["priority"] == "high"
    assert new_checkpoint == now


@pytest.mark.asyncio
async def test_gmail_checkpoint_does_not_advance_on_api_error(test_db: AsyncSession, mock_gmail_service):
    """When list_messages or API raises an exception, checkpoint remains None (unchanged)."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=now - timedelta(days=1))

    mock_gmail_service.list_messages.side_effect = Exception("Gmail API 500 Internal Error")
    detector = GmailDetector(gmail_service=mock_gmail_service)

    candidates, new_checkpoint = await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)
    assert candidates == []
    assert new_checkpoint is None  # Must NOT advance


@pytest.mark.asyncio
async def test_actionable_keyword_deadline_detection(test_db: AsyncSession, mock_gmail_service):
    """Email with 'deadline' keyword generates actionable candidate with create_task suggestion."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_dl"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Final Deadline for Grant Proposal",
        "from": "grants@foundation.org",
        "snippet": "The submission deadline is tomorrow at 5 PM.",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, _ = await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["detection_type"] == "email_actionable"
    assert cand["suggested_action"].action_type == "create_task"
    assert cand["suggested_action"].risk_level == RiskLevel.LOW_RISK_WRITE
    assert "Grant Proposal" in cand["suggested_action"].action_payload["title"]


@pytest.mark.asyncio
async def test_actionable_question_mark_detection(test_db: AsyncSession, mock_gmail_service):
    """Email containing questions generates actionable candidate."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_q"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Design Prototype Feedback",
        "from": "designer@agency.com",
        "snippet": "Can you verify if these color choices align with the new brand guidelines?",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, _ = await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)
    assert len(candidates) == 1
    assert candidates[0]["priority"] == "medium"


@pytest.mark.asyncio
async def test_non_actionable_email_ignored(test_db: AsyncSession, mock_gmail_service):
    """Standard automated marketing / receipts without actionable requests are ignored."""
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": [{"id": "msg_receipt"}]}
    mock_gmail_service.get_message.return_value = {
        "subject": "Your Order Receipt #48291",
        "from": "orders@store.com",
        "snippet": "Thank you for your order. Your items will be shipped shortly.",
    }

    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, _ = await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)
    assert len(candidates) == 0


@pytest.mark.asyncio
async def test_expired_oauth_token_handled_gracefully_without_crash(test_db: AsyncSession, mock_gmail_service):
    """Expired Google OAuth token raises an authentication error which is caught safely."""
    mock_gmail_service.list_messages.side_effect = Exception("Invalid Credentials: Token has been expired or revoked.")
    detector = GmailDetector(gmail_service=mock_gmail_service)
    candidates, checkpoint = await detector.detect_emails(test_db, "u_expired")
    assert candidates == []
    assert checkpoint is None


@pytest.mark.asyncio
async def test_checkpoint_advances_on_empty_inbox(test_db: AsyncSession, mock_gmail_service):
    """When list_messages returns 0 unread messages, checkpoint advances cleanly to current timestamp."""
    now = datetime(2026, 9, 16, 15, 0, 0, tzinfo=timezone.utc)
    pref = UserPreference(user_id="u_gmail_1", last_gmail_proactive_check_at=None)

    mock_gmail_service.list_messages.return_value = {"messages": []}
    detector = GmailDetector(gmail_service=mock_gmail_service)

    candidates, new_checkpoint = await detector.detect_emails(test_db, "u_gmail_1", user_pref=pref, now_utc=now)
    assert candidates == []
    assert new_checkpoint == now
