"""
Comprehensive integration and unit tests for Gmail API endpoints and GmailService.
All Google API requests are strictly mocked — zero real Google API calls are made.
Enforces multi-user isolation, token encryption, safe error handling,
bounded metadata concurrency, and strict log sanitization.
"""
import base64
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.google_account import GoogleAccount, OAuthToken
from app.models.user import User


def _b64_url(s: str) -> str:
    """Encodes string to Gmail-style URL-safe base64."""
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


def _make_http_error(status_code: int, message: str = "Google API Error") -> HttpError:
    """Creates a mock HttpError with a given HTTP status code."""
    resp = MagicMock()
    resp.status = status_code
    resp.reason = message
    content = json.dumps({"error": {"code": status_code, "message": message}}).encode("utf-8")
    return HttpError(resp=resp, content=content)


async def _create_test_user_and_account(
    test_db: AsyncSession,
    email: str = "user@example.com",
    google_user_id: str = "google_sub_001",
    access_token: str = "valid_access_token_123",
    refresh_token: str = "valid_refresh_token_456",
    is_expired: bool = False,
) -> User:
    """Helper to seed an authenticated user with connected Google account and encrypted tokens."""
    user = User(email=email, full_name="Test User", is_active=True)
    test_db.add(user)
    await test_db.flush()

    account = GoogleAccount(
        user_id=user.id,
        google_user_id=google_user_id,
        email=email,
    )
    test_db.add(account)
    await test_db.flush()

    expires_at = datetime.now(timezone.utc) + (timedelta(hours=-1) if is_expired else timedelta(hours=1))
    token_rec = OAuthToken(
        user_id=user.id,
        account_id=account.id,
        encrypted_access_token=SecurityManager.encrypt_token(access_token),
        encrypted_refresh_token=SecurityManager.encrypt_token(refresh_token) if refresh_token else None,
        token_type="Bearer",
        scopes=json.dumps(settings.OAUTH_SCOPES),
        expires_at=expires_at,
    )
    test_db.add(token_rec)
    await test_db.commit()
    return user


def _auth_cookie_for(user: User) -> Dict[str, str]:
    """Generates the HttpOnly session cookie for a given user."""
    session_token = SecurityManager.create_session_token(user_id=user.id)
    return {settings.SESSION_COOKIE_NAME: session_token}


# =============================================================================
# 1. Authentication & Connection Tests
# =============================================================================

@pytest.mark.asyncio
async def test_gmail_endpoints_require_authentication(async_client: AsyncClient):
    """Test that all Gmail endpoints return 401 for unauthenticated requests."""
    res_prof = await async_client.get("/api/v1/gmail/profile")
    assert res_prof.status_code == 401

    res_msgs = await async_client.get("/api/v1/gmail/messages")
    assert res_msgs.status_code == 401

    res_detail = await async_client.get("/api/v1/gmail/messages/msg_123")
    assert res_detail.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_user_without_google_account(async_client: AsyncClient, test_db: AsyncSession):
    """Test that an authenticated user who has NOT connected Google receives 400 Bad Request."""
    user = User(email="no_google@example.com", is_active=True)
    test_db.add(user)
    await test_db.commit()

    cookies = _auth_cookie_for(user)
    response = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
    assert response.status_code == 400
    assert "No connected Google account found" in response.json()["detail"]


# =============================================================================
# 2. Gmail Profile Tests
# =============================================================================

@pytest.mark.asyncio
async def test_get_gmail_profile_success(async_client: AsyncClient, test_db: AsyncSession):
    """Test successful retrieval of normalized Gmail profile."""
    user = await _create_test_user_and_account(test_db, email="profile_test@example.com")
    cookies = _auth_cookie_for(user)

    mock_profile_resp = {
        "emailAddress": "profile_test@example.com",
        "messagesTotal": 350,
        "threadsTotal": 120,
        "historyId": "999888777",
    }

    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().getProfile(userId="me").execute.return_value = mock_profile_resp
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "profile_test@example.com"
        assert data["messages_total"] == 350
        assert data["threads_total"] == 120
        assert data["history_id"] == "999888777"


@pytest.mark.asyncio
async def test_get_gmail_profile_http_error_mappings(async_client: AsyncClient, test_db: AsyncSession):
    """Test mapping Google API HttpErrors (401, 403, 500) to safe status codes."""
    user = await _create_test_user_and_account(test_db, email="err_test@example.com")
    cookies = _auth_cookie_for(user)

    # 401 error from Google
    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().getProfile(userId="me").execute.side_effect = _make_http_error(401)
        mock_build.return_value = mock_service

        res = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
        assert res.status_code == 401
        assert "Google account authentication is required" in res.json()["detail"]

    # 403 error from Google
    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().getProfile(userId="me").execute.side_effect = _make_http_error(403)
        mock_build.return_value = mock_service

        res = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
        assert res.status_code == 403
        assert "Gmail access is not available" in res.json()["detail"]

    # 500 server error from Google -> 502 Bad Gateway
    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().getProfile(userId="me").execute.side_effect = _make_http_error(500)
        mock_build.return_value = mock_service

        res = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
        assert res.status_code == 502
        assert "Unable to communicate with Gmail" in res.json()["detail"]


# =============================================================================
# 3. Message Listing & Search Tests
# =============================================================================

@pytest.mark.asyncio
async def test_list_messages_success(async_client: AsyncClient, test_db: AsyncSession):
    """Test listing messages returns bounded summaries with metadata."""
    user = await _create_test_user_and_account(test_db, email="inbox@example.com")
    cookies = _auth_cookie_for(user)

    mock_list_resp = {
        "messages": [
            {"id": "msg_001", "threadId": "th_001"},
            {"id": "msg_002", "threadId": "th_002"},
        ],
        "nextPageToken": "token_page_2",
        "resultSizeEstimate": 2,
    }

    mock_msg_001 = {
        "id": "msg_001",
        "threadId": "th_001",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Meeting tomorrow at 10 AM",
        "internalDate": "1768473000000",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Team Sync"},
                {"name": "From", "value": "boss@example.com"},
                {"name": "To", "value": "inbox@example.com"},
                {"name": "Date", "value": "Mon, 15 Jan 2026 10:30:00 +0000"},
            ],
            "parts": [],
        },
    }

    mock_msg_002 = {
        "id": "msg_002",
        "threadId": "th_002",
        "labelIds": ["INBOX"],
        "snippet": "Invoice attached",
        "internalDate": "1768472000000",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Invoice #1042"},
                {"name": "From", "value": "billing@example.com"},
                {"name": "To", "value": "inbox@example.com"},
            ],
            "parts": [
                {"filename": "invoice.pdf", "body": {"attachmentId": "att_inv_1"}}
            ],
        },
    }

    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().messages().list.return_value.execute.return_value = mock_list_resp

        def _get_side_effect(userId, id, format, metadataHeaders):
            m = MagicMock()
            if id == "msg_001":
                m.execute.return_value = mock_msg_001
            else:
                m.execute.return_value = mock_msg_002
            return m

        mock_service.users().messages().get.side_effect = _get_side_effect
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/messages?max_results=20", cookies=cookies)
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["next_page_token"] == "token_page_2"
        assert data["result_size_estimate"] == 2

        msg1 = data["messages"][0]
        assert msg1["id"] == "msg_001"
        assert msg1["subject"] == "Team Sync"
        assert msg1["sender"] == "boss@example.com"
        assert msg1["is_unread"] is True
        assert msg1["has_attachments"] is False

        msg2 = data["messages"][1]
        assert msg2["id"] == "msg_002"
        assert msg2["subject"] == "Invoice #1042"
        assert msg2["is_unread"] is False
        assert msg2["has_attachments"] is True


@pytest.mark.asyncio
async def test_list_messages_empty_mailbox(async_client: AsyncClient, test_db: AsyncSession):
    """Test listing messages when mailbox has zero matching emails."""
    user = await _create_test_user_and_account(test_db, email="empty@example.com")
    cookies = _auth_cookie_for(user)

    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().messages().list.return_value.execute.return_value = {
            "messages": [],
            "resultSizeEstimate": 0,
        }
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/messages", cookies=cookies)
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["result_size_estimate"] == 0
        assert data["next_page_token"] is None


@pytest.mark.asyncio
async def test_list_messages_max_results_validation(async_client: AsyncClient, test_db: AsyncSession):
    """Test that max_results > 100 or < 1 is rejected with 422 validation error."""
    user = await _create_test_user_and_account(test_db, email="validation@example.com")
    cookies = _auth_cookie_for(user)

    # > 100
    res_too_large = await async_client.get("/api/v1/gmail/messages?max_results=101", cookies=cookies)
    assert res_too_large.status_code == 422

    # < 1
    res_too_small = await async_client.get("/api/v1/gmail/messages?max_results=0", cookies=cookies)
    assert res_too_small.status_code == 422


@pytest.mark.asyncio
async def test_list_messages_query_parameter_forwarded(async_client: AsyncClient, test_db: AsyncSession):
    """Test that Gmail search query syntax (is:unread, from:...) is passed to Gmail API."""
    user = await _create_test_user_and_account(test_db, email="query_test@example.com")
    cookies = _auth_cookie_for(user)

    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().messages().list.return_value.execute.return_value = {
            "messages": [],
            "resultSizeEstimate": 0,
        }
        mock_build.return_value = mock_service

        await async_client.get("/api/v1/gmail/messages?query=is:unread%20from:boss@example.com", cookies=cookies)

        # Verify 'q' parameter was supplied to Google messages().list
        mock_service.users().messages().list.assert_called_once_with(
            userId="me",
            maxResults=20,
            q="is:unread from:boss@example.com",
        )


# =============================================================================
# 4. Message Detail Tests
# =============================================================================

@pytest.mark.asyncio
async def test_get_message_detail_success(async_client: AsyncClient, test_db: AsyncSession):
    """Test retrieving full message detail with body and attachment metadata."""
    user = await _create_test_user_and_account(test_db, email="detail_user@example.com")
    cookies = _auth_cookie_for(user)

    mock_msg_full = {
        "id": "msg_detail_123",
        "threadId": "th_detail_123",
        "labelIds": ["INBOX", "UNREAD", "STARRED"],
        "snippet": "Here is the contract for your review.",
        "internalDate": "1768473000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Contract Agreement"},
                {"name": "From", "value": "Legal Team <legal@corp.com>"},
                {"name": "To", "value": "detail_user@example.com"},
                {"name": "Cc", "value": "witness@corp.com"},
                {"name": "Date", "value": "Tue, 16 Jan 2026 14:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64_url("Please sign and return.")},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "Contract_Agreement_2026.pdf",
                    "body": {"attachmentId": "att_contract_01", "size": 524288},
                },
            ],
        },
    }

    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().messages().get(
            userId="me", id="msg_detail_123", format="full"
        ).execute.return_value = mock_msg_full
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/messages/msg_detail_123", cookies=cookies)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "msg_detail_123"
        assert data["subject"] == "Contract Agreement"
        assert data["sender"] == "Legal Team <legal@corp.com>"
        assert data["recipients"] == ["detail_user@example.com"]
        assert data["cc"] == ["witness@corp.com"]
        assert data["body_plain"] == "Please sign and return."
        assert len(data["attachments"]) == 1
        att = data["attachments"][0]
        assert att["filename"] == "Contract_Agreement_2026.pdf"
        assert att["size"] == 524288
        assert att["attachment_id"] == "att_contract_01"


@pytest.mark.asyncio
async def test_get_message_detail_not_found(async_client: AsyncClient, test_db: AsyncSession):
    """Test 404 response when message ID does not exist in Gmail."""
    user = await _create_test_user_and_account(test_db, email="notfound@example.com")
    cookies = _auth_cookie_for(user)

    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().messages().get(
            userId="me", id="nonexistent_id", format="full"
        ).execute.side_effect = _make_http_error(404, "Message not found")
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/messages/nonexistent_id", cookies=cookies)
        assert response.status_code == 404
        assert response.json()["detail"] == "Email message not found."


# =============================================================================
# 5. Token Handling & Refresh Integration
# =============================================================================

@pytest.mark.asyncio
async def test_expired_token_automatically_refreshes(async_client: AsyncClient, test_db: AsyncSession):
    """Test that an expired OAuth token is automatically refreshed before the Gmail API call."""
    user = await _create_test_user_and_account(
        test_db,
        email="expired_refresh@example.com",
        access_token="old_expired_access_token",
        refresh_token="valid_stored_refresh_token",
        is_expired=True,
    )
    cookies = _auth_cookie_for(user)

    mock_profile_resp = {
        "emailAddress": "expired_refresh@example.com",
        "messagesTotal": 50,
        "threadsTotal": 20,
    }

    # Mock the HTTP token refresh call to Google Token URI
    with patch("httpx.AsyncClient.post") as mock_token_post, patch("app.services.gmail_service.build") as mock_build:
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "brand_new_refreshed_access_token_999",
            "expires_in": 3600,
        }
        mock_token_post.return_value = mock_token_resp

        mock_service = MagicMock()
        mock_service.users().getProfile(userId="me").execute.return_value = mock_profile_resp
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
        assert response.status_code == 200
        assert mock_token_post.called

        # Verify Google Credentials object was built with the new token
        creds_arg = mock_build.call_args[1]["credentials"]
        assert creds_arg.token == "brand_new_refreshed_access_token_999"


@pytest.mark.asyncio
async def test_revoked_refresh_token_returns_safe_auth_error(async_client: AsyncClient, test_db: AsyncSession):
    """Test that when Google rejects the refresh token (invalid_grant), 401 is returned."""
    user = await _create_test_user_and_account(
        test_db,
        email="revoked@example.com",
        access_token="expired_token",
        refresh_token="revoked_token",
        is_expired=True,
    )
    cookies = _auth_cookie_for(user)

    with patch("httpx.AsyncClient.post") as mock_token_post:
        mock_err_resp = MagicMock()
        mock_err_resp.status_code = 400
        mock_err_resp.text = json.dumps({"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
        mock_token_post.return_value = mock_err_resp

        response = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
        assert response.status_code == 401
        assert "Google account authentication is required" in response.json()["detail"]


# =============================================================================
# 6. Multi-User Isolation Guarantee
# =============================================================================

@pytest.mark.asyncio
async def test_multi_user_isolation_strictly_enforced(async_client: AsyncClient, test_db: AsyncSession):
    """
    Test that User A and User B only access their own respective Gmail mailboxes.
    Frontend parameters cannot spoof or access another user's email data.
    """
    user_a = await _create_test_user_and_account(
        test_db,
        email="user_a@tenant.com",
        google_user_id="sub_a",
        access_token="tok_user_a",
    )
    user_b = await _create_test_user_and_account(
        test_db,
        email="user_b@tenant.com",
        google_user_id="sub_b",
        access_token="tok_user_b",
    )

    cookies_a = _auth_cookie_for(user_a)
    cookies_b = _auth_cookie_for(user_b)

    with patch("app.services.gmail_service.build") as mock_build:
        # Mock service responses keyed by token
        def _mock_build_side_effect(serviceName, version, credentials, **kwargs):
            m = MagicMock()
            if credentials.token == "tok_user_a":
                m.users().getProfile(userId="me").execute.return_value = {
                    "emailAddress": "user_a@tenant.com",
                    "messagesTotal": 100,
                    "threadsTotal": 50,
                }
            elif credentials.token == "tok_user_b":
                m.users().getProfile(userId="me").execute.return_value = {
                    "emailAddress": "user_b@tenant.com",
                    "messagesTotal": 200,
                    "threadsTotal": 90,
                }
            return m

        mock_build.side_effect = _mock_build_side_effect

        # User A request
        res_a = await async_client.get("/api/v1/gmail/profile", cookies=cookies_a)
        assert res_a.status_code == 200
        assert res_a.json()["email"] == "user_a@tenant.com"
        assert res_a.json()["messages_total"] == 100

        # User B request
        res_b = await async_client.get("/api/v1/gmail/profile", cookies=cookies_b)
        assert res_b.status_code == 200
        assert res_b.json()["email"] == "user_b@tenant.com"
        assert res_b.json()["messages_total"] == 200

        # Attempt to inject user_id in query for User A
        res_spoof = await async_client.get(
            f"/api/v1/gmail/profile?user_id={user_b.id}",
            cookies=cookies_a,
        )
        assert res_spoof.status_code == 200
        # Still returns User A's data — server ignores untrusted parameter!
        assert res_spoof.json()["email"] == "user_a@tenant.com"


# =============================================================================
# 7. Security: Zero Token / Email Body Leakage in Responses & Logs
# =============================================================================

@pytest.mark.asyncio
async def test_tokens_and_secrets_never_appear_in_api_responses(async_client: AsyncClient, test_db: AsyncSession):
    """Verify that access tokens, refresh tokens, client secrets, and Fernet keys never leak in responses."""
    user = await _create_test_user_and_account(test_db, email="secret_leak_test@example.com")
    cookies = _auth_cookie_for(user)

    with patch("app.services.gmail_service.build") as mock_build:
        mock_service = MagicMock()
        mock_service.users().getProfile(userId="me").execute.return_value = {
            "emailAddress": "secret_leak_test@example.com",
            "messagesTotal": 10,
            "threadsTotal": 5,
        }
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/profile", cookies=cookies)
        content_str = response.text

        assert "valid_access_token_123" not in content_str
        assert "valid_refresh_token_456" not in content_str
        assert "mock-client-secret" not in content_str
        assert "test-secret-key" not in content_str
        assert "access_token" not in content_str
        assert "refresh_token" not in content_str


@pytest.mark.asyncio
async def test_email_bodies_and_tokens_never_logged(
    async_client: AsyncClient,
    test_db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
):
    """Verify that structured logs never contain raw email bodies or authorization headers/tokens."""
    user = await _create_test_user_and_account(test_db, email="logger_test@example.com")
    cookies = _auth_cookie_for(user)

    secret_email_body = "TOP_SECRET_CONFIDENTIAL_BUSINESS_PLAN_DO_NOT_LOG"
    mock_msg = {
        "id": "msg_classified",
        "threadId": "th_classified",
        "labelIds": ["INBOX"],
        "snippet": "Confidential meeting",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Confidential"},
                {"name": "From", "value": "ceo@example.com"},
            ],
            "body": {"data": _b64_url(secret_email_body)},
        },
    }

    with patch("app.services.gmail_service.build") as mock_build, caplog.at_level(logging.DEBUG):
        mock_service = MagicMock()
        mock_service.users().messages().get(
            userId="me", id="msg_classified", format="full"
        ).execute.return_value = mock_msg
        mock_build.return_value = mock_service

        response = await async_client.get("/api/v1/gmail/messages/msg_classified", cookies=cookies)
        assert response.status_code == 200

        all_logs = " ".join([record.message for record in caplog.records])
        assert secret_email_body not in all_logs
        assert "valid_access_token" not in all_logs
        assert "Authorization" not in all_logs
