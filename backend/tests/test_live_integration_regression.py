"""
Regression tests for Live Integration fixes:
1. OAuth scope verification, tokeninfo parsing, reconnect flow parameters.
2. Gmail interview retrieval with time-aware classification (past vs upcoming/pending).
3. Gemini 429/503 bounded retries, fast-fail on excessive delays, and multi-turn message merging.
"""
import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from app.services.oauth_service import OAuthService, InsufficientScopesError
from app.services.interview_classifier import classify_interview_email, InterviewStatus, parse_temporal_cutoff
from app.ai.providers.gemini_provider import GeminiProvider
from app.ai.providers.base import LLMServiceUnavailableError, LLMRateLimitError, LLMMessage, LLMToolCall, LLMResponse


@pytest.mark.asyncio
async def test_oauth_create_authorization_url_reconnect():
    """Verify authorization URL includes select_account and prompt=consent when reconnect=True."""
    with patch("app.services.oauth_service.settings") as mock_settings:
        mock_settings.GOOGLE_CLIENT_ID = "test-client-id"
        mock_settings.GOOGLE_CLIENT_SECRET = "test-secret"
        mock_settings.GOOGLE_REDIRECT_URI = "http://localhost:8000/auth/callback"
        mock_settings.GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
        mock_settings.OAUTH_SCOPES = [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.readonly",
        ]

        # Normal connect
        url_normal = OAuthService.create_authorization_url(state="test-state-1", reconnect=False)
        assert "prompt=consent" in url_normal
        assert "include_granted_scopes=true" in url_normal
        assert "state=test-state-1" in url_normal

        # Reconnect
        url_reconnect = OAuthService.create_authorization_url(state="test-state-2", reconnect=True)
        assert "prompt=consent+select_account" in url_reconnect or "prompt=consent%20select_account" in url_reconnect
        assert "include_granted_scopes=false" in url_reconnect
        assert "state=test-state-2" in url_reconnect


@pytest.mark.asyncio
async def test_oauth_verify_token_scopes():
    """Verify verify_token_scopes parses Google tokeninfo scope response correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "issued_to": "123.apps.googleusercontent.com",
        "scope": "https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gmail.readonly openid",
    }

    with patch("httpx.AsyncClient.get", return_value=mock_response):
        scopes = await OAuthService.verify_token_scopes("mock-access-token")
        assert len(scopes) == 3
        assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
        assert "https://www.googleapis.com/auth/calendar.readonly" not in scopes


@pytest.mark.asyncio
async def test_oauth_has_required_scope():
    """Verify scope checking logic handles exact matches and short aliases."""
    mock_db = MagicMock()
    with patch("app.services.oauth_service.OAuthService.get_user_granted_scopes", return_value=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]):
        has_gmail = await OAuthService.has_required_scope(mock_db, "user-123", "https://www.googleapis.com/auth/gmail.readonly")
        has_calendar = await OAuthService.has_required_scope(mock_db, "user-123", "https://www.googleapis.com/auth/calendar.readonly")

        assert has_gmail is True
        assert has_calendar is False


def test_interview_classifier_upcoming_vs_past():
    """Verify interview classifier accurately distinguishes upcoming from past interviews."""
    ref_now = datetime(2026, 9, 24, 18, 0, 0, tzinfo=timezone.utc)

    # 1. Past interview
    past_text = "Your interview was scheduled for September 20, 2026 at 2:00 PM UTC."
    past_result = classify_interview_email(
        subject="Interview Invitation",
        body_or_snippet=past_text,
        email_received_dt=ref_now - timedelta(days=5),
        reference_cutoff=ref_now,
        now_ref=ref_now,
    )
    assert past_result["status"] in [InterviewStatus.EXPIRED_PAST, InterviewStatus.HISTORICAL]
    assert past_result["is_pending_or_upcoming"] is False

    # 2. Upcoming interview
    upcoming_text = "Your technical interview is scheduled for September 28, 2026 at 3:00 PM UTC."
    upcoming_result = classify_interview_email(
        subject="Technical Interview Confirmation",
        body_or_snippet=upcoming_text,
        email_received_dt=ref_now - timedelta(hours=2),
        reference_cutoff=ref_now,
        now_ref=ref_now,
    )
    assert upcoming_result["status"] == InterviewStatus.UPCOMING
    assert upcoming_result["is_pending_or_upcoming"] is True

    # 3. Action pending (slot booking request with future deadline)
    action_text = "Please select your interview slot by September 30, 2026."
    action_result = classify_interview_email(
        subject="Invitation: Select your interview slot",
        body_or_snippet=action_text,
        email_received_dt=ref_now - timedelta(hours=1),
        reference_cutoff=ref_now,
        now_ref=ref_now,
    )
    assert action_result["status"] == InterviewStatus.PENDING_ACTION
    assert action_result["is_pending_or_upcoming"] is True


@pytest.mark.asyncio
async def test_gemini_503_bounded_retry():
    """Verify GeminiProvider retries transient 503 errors with bounded retry count."""
    provider = GeminiProvider(api_key="fake-key", model_name="gemini-3.5-flash")

    # Mock httpx client to return 503 twice then success
    mock_503_resp = MagicMock()
    mock_503_resp.status_code = 503
    mock_503_resp.text = "Service Unavailable"
    mock_503_resp.headers = {"Retry-After": "1"}

    mock_200_resp = MagicMock()
    mock_200_resp.status_code = 200
    mock_200_resp.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "Hello! I am ready."}],
                "role": "model",
            },
            "finishReason": "STOP",
        }],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        },
    }

    call_count = 0
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return mock_503_resp
        return mock_200_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        with patch("asyncio.sleep", return_value=None):
            resp = await provider.generate_response([LLMMessage(role="user", content="Hi")])
            assert resp.content == "Hello! I am ready."
            assert call_count == 3


@pytest.mark.asyncio
async def test_gemini_429_delay_ceiling_fast_fail():
    """Verify GeminiProvider fast-fails if Retry-After exceeds delay ceiling."""
    provider = GeminiProvider(api_key="fake-key", model_name="gemini-3.5-flash")

    mock_429_resp = MagicMock()
    mock_429_resp.status_code = 429
    mock_429_resp.text = "RESOURCE_EXHAUSTED"
    mock_429_resp.headers = {"Retry-After": "120"}  # 120s exceeds MAX_RETRY_DELAY (40s)

    with patch("httpx.AsyncClient.post", return_value=mock_429_resp):
        with pytest.raises(LLMRateLimitError) as exc_info:
            await provider.generate_response([LLMMessage(role="user", content="Hi")])
        assert exc_info.value.retry_after == 120.0


def test_gemini_payload_merging_for_multi_turn_function_calling():
    """Verify consecutive tool messages are merged into a single user turn."""
    provider = GeminiProvider(api_key="fake-key", model_name="gemini-3.5-flash")

    messages = [
        LLMMessage(role="user", content="Search my emails"),
        LLMMessage(
            role="model",
            content=None,
            tool_calls=[LLMToolCall(id="c1", name="search_gmail", arguments={"query": "interview"})]
        ),
        LLMMessage(
            role="tool",
            tool_name="search_gmail",
            tool_response={"status": "success", "count": 2},
        ),
        LLMMessage(
            role="tool",
            tool_name="get_gmail_profile",
            tool_response={"status": "success", "profile": "rajsingh190904@gmail.com"},
        ),
    ]

    contents = provider._build_contents_payload(messages)
    # The last two tool messages should be merged into ONE turn with role "user"
    assert len(contents) == 3
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert contents[2]["role"] == "user"
    assert len(contents[2]["parts"]) == 2
    assert "functionResponse" in contents[2]["parts"][0]
    assert "functionResponse" in contents[2]["parts"][1]


@pytest.mark.asyncio
async def test_orchestrator_resilient_synthesis_fallback_on_429():
    """Verify AgentOrchestrator synthesizes tool data even if final synthesis turn hits 429."""
    from app.ai.agent.orchestrator import AgentOrchestrator
    from app.models.user import User

    mock_provider = MagicMock()
    # Turn 1: Return search_gmail tool call
    # Turn 2: Raise LLMRateLimitError
    turn = 0
    async def mock_generate_response(*args, **kwargs):
        nonlocal turn
        turn += 1
        if turn == 1:
            return LLMResponse(
                content=None,
                tool_calls=[LLMToolCall(id="t1", name="search_gmail", arguments={"query": "interview"})],
            )
        raise LLMRateLimitError("Gemini API rate limit reached.", retry_after=59.0)

    mock_provider.generate_response = mock_generate_response
    mock_provider.model_name = "gemini-3.5-flash"

    orchestrator = AgentOrchestrator(provider=mock_provider)
    user = User(id="user-test-429", email="tester@example.com")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    # Mock tool executor to return search result with upcoming interview
    with patch("app.ai.agent.tool_executor.ToolExecutor.execute_tool") as mock_exec:
        mock_exec.return_value = MagicMock(
            status="completed",
            friendly_summary="Found 1 message",
            confirmation_challenge=None,
            result_payload={
                "source": "gmail",
                "status": "success",
                "count": 1,
                "messages": [
                    {
                        "id": "msg-123",
                        "subject": "Google Technical Interview Invitation",
                        "sender": "recruiter@google.com",
                        "timestamp": "2026-09-28T15:00:00Z",
                        "interview_temporal_status": "UPCOMING",
                        "interview_scheduled_time": "September 28, 2026 at 3:00 PM UTC",
                        "is_pending_or_upcoming": True,
                    }
                ],
            },
        )
        resp = await orchestrator.process_message(
            user=user,
            db=mock_db,
            message="TELL ME UPCOMING INTERVIEW DETAILS",
        )

        assert resp is not None
        assert "Google Technical Interview Invitation" in resp.message
        assert "Upcoming & Pending Interviews" in resp.message
        assert len(resp.tool_activities) == 1
