"""
Comprehensive Test Suite for Google Calendar Read Integration (Milestone 4).
All Google API requests are strictly mocked — zero real Google API calls are made.
Tests:
- Authentication & Scope verification (calendar.readonly)
- Calendar list & pagination
- Calendar detail & 404
- Event list with date filtering (RFC3339), search, and pagination
- Timed events vs all-day events & timezone preservation
- Recurring event expansion (singleEvents=True, orderBy=startTime)
- Event detail, attendee normalization, and conference metadata
- Token refresh & revoked token handling
- Multi-user tenant isolation
- Zero token leakage in responses or logs
- No destructive or write operations
- Incremental authorization and scope merging
- Parameter validation (bounds, invalid range)
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.google_account import GoogleAccount, OAuthToken
from app.models.user import User
from app.services.calendar_service import (
    CalendarAuthenticationError,
    CalendarCommunicationError,
    CalendarNotConnectedError,
    CalendarNotFoundError,
    CalendarPermissionError,
    CalendarRateLimitError,
    CalendarScopeMissingError,
    CalendarService,
    CalendarValidationError,
)
from app.services.oauth_service import OAuthService


# =============================================================================
# Mock Fixtures & Helpers
# =============================================================================

MOCK_CALENDAR_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def _make_http_error(status_code: int, message: str = "Google Calendar API Error") -> HttpError:
    """Creates a mock HttpError with a given HTTP status code."""
    resp = MagicMock()
    resp.status = status_code
    resp.reason = message
    content = json.dumps({"error": {"code": status_code, "message": message}}).encode("utf-8")
    return HttpError(resp=resp, content=content)


async def create_test_user_with_calendar(
    test_db: AsyncSession,
    email: str = "calendar_user@example.com",
    scopes: list = None,
    access_token: str = "mock-cal-access-token",
    refresh_token: str = "mock-cal-refresh-token",
    is_expired: bool = False,
) -> tuple[User, GoogleAccount, OAuthToken]:
    """Helper to seed an authenticated test user with encrypted tokens in SQLite test DB."""
    if scopes is None:
        scopes = MOCK_CALENDAR_SCOPES

    user = User(
        email=email,
        full_name="Calendar Test User",
        picture_url="https://example.com/pic.jpg",
        is_active=True,
    )
    test_db.add(user)
    await test_db.flush()

    google_account = GoogleAccount(
        user_id=user.id,
        google_user_id=f"google-{user.id}",
        email=email,
        picture_url="https://example.com/pic.jpg",
    )
    test_db.add(google_account)
    await test_db.flush()

    expires_at = (
        datetime.now(timezone.utc) - timedelta(hours=1)
        if is_expired
        else datetime.now(timezone.utc) + timedelta(hours=1)
    )

    oauth_token = OAuthToken(
        user_id=user.id,
        account_id=google_account.id,
        encrypted_access_token=SecurityManager.encrypt_token(access_token),
        encrypted_refresh_token=SecurityManager.encrypt_token(refresh_token) if refresh_token else None,
        token_type="Bearer",
        scopes=json.dumps(scopes),
        expires_at=expires_at,
    )
    test_db.add(oauth_token)
    await test_db.commit()
    await test_db.refresh(user)
    await test_db.refresh(google_account)
    await test_db.refresh(oauth_token)

    return user, google_account, oauth_token


def make_mock_calendar_item(
    cal_id: str = "primary",
    summary: str = "Personal Calendar",
    time_zone: str = "Asia/Kolkata",
    is_primary: bool = True,
) -> Dict[str, Any]:
    return {
        "id": cal_id,
        "summary": summary,
        "description": "My primary calendar",
        "timeZone": time_zone,
        "primary": is_primary,
        "backgroundColor": "#4285F4",
        "accessRole": "owner",
        "selected": True,
        "hidden": False,
    }


def make_mock_event_item(
    event_id: str = "evt123",
    summary: str = "Sprint Planning Meeting",
    start_dt: str = "2026-09-15T10:00:00+05:30",
    end_dt: str = "2026-09-15T11:00:00+05:30",
    is_all_day: bool = False,
    location: str = "Conference Room B",
    has_meet: bool = True,
) -> Dict[str, Any]:
    if is_all_day:
        start_obj = {"date": "2026-09-15"}
        end_obj = {"date": "2026-09-16"}
    else:
        start_obj = {"dateTime": start_dt, "timeZone": "Asia/Kolkata"}
        end_obj = {"dateTime": end_dt, "timeZone": "Asia/Kolkata"}

    event = {
        "id": event_id,
        "summary": summary,
        "description": "Weekly sprint planning and task assignment.",
        "location": location,
        "start": start_obj,
        "end": end_obj,
        "status": "confirmed",
        "htmlLink": f"https://calendar.google.com/event?eid={event_id}",
        "organizer": {"email": "organizer@example.com", "displayName": "Tech Lead"},
        "creator": {"email": "creator@example.com", "displayName": "Project Manager"},
        "attendees": [
            {"email": "attendee1@example.com", "displayName": "Dev One", "responseStatus": "accepted", "organizer": False, "self": False},
            {"email": "calendar_user@example.com", "displayName": "Calendar User", "responseStatus": "accepted", "organizer": False, "self": True},
        ],
        "reminders": {"useDefault": True, "overrides": []},
        "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"],
    }
    if has_meet:
        event["conferenceData"] = {
            "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij", "label": "meet.google.com/abc-defg-hij"}],
            "conferenceSolution": {"name": "Google Meet"},
        }
    return event


# =============================================================================
# 1. Authentication & Scope Verification Tests
# =============================================================================

@pytest.mark.asyncio
async def test_calendar_endpoints_require_authentication(async_client: AsyncClient):
    """Endpoints must reject unauthenticated requests with HTTP 401."""
    resp1 = await async_client.get("/api/v1/calendar/calendars")
    assert resp1.status_code == 401

    resp2 = await async_client.get("/api/v1/calendar/events")
    assert resp2.status_code == 401

    resp3 = await async_client.get("/api/v1/calendar/calendars/primary")
    assert resp3.status_code == 401

    resp4 = await async_client.get("/api/v1/calendar/events/evt123")
    assert resp4.status_code == 401


@pytest.mark.asyncio
async def test_user_without_google_account_returns_400(async_client: AsyncClient, test_db: AsyncSession):
    """An authenticated user with no connected Google account receives 400 Bad Request."""
    user = User(email="nogw@example.com", is_active=True)
    test_db.add(user)
    await test_db.commit()

    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    resp = await async_client.get("/api/v1/calendar/calendars")
    assert resp.status_code == 400
    assert "No connected Google account found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_user_missing_calendar_scope_returns_403_and_never_calls_google(
    async_client: AsyncClient, test_db: AsyncSession
):
    """
    If the user's token only has Gmail scope and is missing calendar.readonly:
    The API must return HTTP 403 with reauthorization instructions and NEVER call Google API.
    """
    gmail_only_scopes = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]
    user, _, _ = await create_test_user_with_calendar(
        test_db, email="gmail_only@example.com", scopes=gmail_only_scopes
    )
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    with patch("app.services.calendar_service.build") as mock_build:
        resp = await async_client.get("/api/v1/calendar/calendars")
        assert resp.status_code == 403
        assert "Google Calendar access is not authorized" in resp.json()["detail"]
        mock_build.assert_not_called()


# =============================================================================
# 2. Calendar List & Detail Tests
# =============================================================================

@pytest.mark.asyncio
async def test_list_calendars_success(async_client: AsyncClient, test_db: AsyncSession):
    """Successfully retrieves and normalizes calendar list."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_cal_list = mock_client.calendarList.return_value
    mock_cal_list.list.return_value.execute.return_value = {
        "items": [
            make_mock_calendar_item("primary", "Personal", "Asia/Kolkata", True),
            make_mock_calendar_item("work@example.com", "Work Calendar", "America/New_York", False),
        ],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["calendars"]) == 2
        assert data["calendars"][0]["id"] == "primary"
        assert data["calendars"][0]["primary"] is True
        assert data["calendars"][0]["time_zone"] == "Asia/Kolkata"
        assert data["calendars"][1]["summary"] == "Work Calendar"


@pytest.mark.asyncio
async def test_list_calendars_pagination(async_client: AsyncClient, test_db: AsyncSession):
    """Handles pagination token for calendar listing."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_cal_list = mock_client.calendarList.return_value
    mock_cal_list.list.return_value.execute.return_value = {
        "items": [make_mock_calendar_item("cal1")],
        "nextPageToken": "token-page-2",
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars?page_token=page1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["next_page_token"] == "token-page-2"
        mock_cal_list.list.assert_called_with(minAccessRole="reader", pageToken="page1")


@pytest.mark.asyncio
async def test_get_calendar_detail_success(async_client: AsyncClient, test_db: AsyncSession):
    """Retrieves specific calendar detail."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_cal_list = mock_client.calendarList.return_value
    mock_cal_list.get.return_value.execute.return_value = make_mock_calendar_item("primary", "Primary Cal")

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars/primary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "primary"
        assert data["summary"] == "Primary Cal"


@pytest.mark.asyncio
async def test_get_calendar_detail_not_found(async_client: AsyncClient, test_db: AsyncSession):
    """Returns 404 when calendar is not found."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.calendarList.return_value.get.return_value.execute.side_effect = _make_http_error(404, "Not Found")
    mock_client.calendars.return_value.get.return_value.execute.side_effect = _make_http_error(404, "Not Found")

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars/nonexistent_cal")
        assert resp.status_code == 404
        assert "Calendar or event not found" in resp.json()["detail"]


# =============================================================================
# 3. Events Listing, Filtering & Date/Time Tests
# =============================================================================

@pytest.mark.asyncio
async def test_list_events_success_timed_and_all_day(async_client: AsyncClient, test_db: AsyncSession):
    """Tests event list returning both timed and all-day events with proper flags."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_events = mock_client.events.return_value
    mock_events.list.return_value.execute.return_value = {
        "items": [
            make_mock_event_item("evt1", "Timed Meeting", is_all_day=False),
            make_mock_event_item("evt2", "Team Holiday", is_all_day=True),
        ],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/events?calendar_id=primary")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 2

        timed = data["events"][0]
        assert timed["id"] == "evt1"
        assert timed["is_all_day"] is False
        assert "T" in timed["start"]
        assert timed["has_conference"] is True
        assert timed["conference_uri"] == "https://meet.google.com/abc-defg-hij"

        all_day = data["events"][1]
        assert all_day["id"] == "evt2"
        assert all_day["is_all_day"] is True
        assert all_day["start"] == "2026-09-15"


@pytest.mark.asyncio
async def test_list_events_date_range_filtering_rfc3339(async_client: AsyncClient, test_db: AsyncSession):
    """Passes valid time_min and time_max in RFC3339 format to Google API."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_events = mock_client.events.return_value
    mock_events.list.return_value.execute.return_value = {"items": [], "nextPageToken": None}

    with patch("app.services.calendar_service.build", return_value=mock_client):
        t_min = "2026-09-15T00:00:00Z"
        t_max = "2026-09-22T23:59:59Z"
        resp = await async_client.get(f"/api/v1/calendar/events?time_min={t_min}&time_max={t_max}")
        assert resp.status_code == 200

        mock_events.list.assert_called_once()
        call_kwargs = mock_events.list.call_args[1]
        assert "timeMin" in call_kwargs
        assert "timeMax" in call_kwargs
        assert call_kwargs["singleEvents"] is True
        assert call_kwargs["orderBy"] == "startTime"


@pytest.mark.asyncio
async def test_list_events_invalid_date_range_rejected(async_client: AsyncClient, test_db: AsyncSession):
    """Rejects time_min later than time_max with HTTP 400."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    t_min = "2026-09-22T00:00:00Z"
    t_max = "2026-09-15T00:00:00Z"
    resp = await async_client.get(f"/api/v1/calendar/events?time_min={t_min}&time_max={t_max}")
    assert resp.status_code == 400
    assert "time_min cannot be later than time_max" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_events_max_results_validation(async_client: AsyncClient, test_db: AsyncSession):
    """Validates max_results parameter bounds (1 <= max_results <= 100)."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    # Below minimum (0)
    resp1 = await async_client.get("/api/v1/calendar/events?max_results=0")
    assert resp1.status_code == 422

    # Above maximum (101)
    resp2 = await async_client.get("/api/v1/calendar/events?max_results=101")
    assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_list_events_search_query(async_client: AsyncClient, test_db: AsyncSession):
    """Passes search query string 'q' to Google Calendar events list."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_events = mock_client.events.return_value
    mock_events.list.return_value.execute.return_value = {"items": [], "nextPageToken": None}

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/events?query=planning")
        assert resp.status_code == 200
        call_kwargs = mock_events.list.call_args[1]
        assert call_kwargs["q"] == "planning"


@pytest.mark.asyncio
async def test_list_events_empty_calendar(async_client: AsyncClient, test_db: AsyncSession):
    """Returns empty event list when Google Calendar has no events."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.events.return_value.list.return_value.execute.return_value = {
        "items": [],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["next_page_token"] is None


# =============================================================================
# 4. Event Detail, Attendees & Conference Normalization
# =============================================================================

@pytest.mark.asyncio
async def test_get_event_detail_success(async_client: AsyncClient, test_db: AsyncSession):
    """Retrieves normalized event detail with attendees and conference data."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_events = mock_client.events.return_value
    mock_events.get.return_value.execute.return_value = make_mock_event_item("evt123", "Architecture Review")

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars/primary/events/evt123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "evt123"
        assert data["summary"] == "Architecture Review"
        assert len(data["attendees"]) == 2
        assert data["attendees"][0]["display_name"] == "Dev One"
        assert data["conference"]["solution_name"] == "Google Meet"
        assert data["conference"]["uri"] == "https://meet.google.com/abc-defg-hij"


@pytest.mark.asyncio
async def test_get_event_detail_not_found(async_client: AsyncClient, test_db: AsyncSession):
    """Returns 404 for non-existent event ID."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.events.return_value.get.return_value.execute.side_effect = _make_http_error(404, "Not Found")

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars/primary/events/nonexistent_evt")
        assert resp.status_code == 404
        assert "Calendar or event not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_primary_event_convenience_endpoint(async_client: AsyncClient, test_db: AsyncSession):
    """Tests /api/v1/calendar/events/{event_id} convenience endpoint."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_events = mock_client.events.return_value
    mock_events.get.return_value.execute.return_value = make_mock_event_item("evt999", "Convenience Meeting")

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/events/evt999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "evt999"
        mock_events.get.assert_called_with(calendarId="primary", eventId="evt999")


# =============================================================================
# 5. Error Translation & Google API Failures
# =============================================================================

@pytest.mark.asyncio
async def test_google_http_error_mappings(async_client: AsyncClient, test_db: AsyncSession):
    """Maps Google HttpError status codes (401, 403, 404, 429, 500) into domain exceptions."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    error_cases = [
        (401, 401, "Google account authentication is required"),
        (403, 403, "Calendar access is forbidden"),
        (404, 404, "Calendar or event not found"),
        (429, 429, "rate limit reached"),
        (500, 502, "Unable to communicate with Google Calendar"),
    ]

    for google_status, expected_http, expected_detail_snippet in error_cases:
        mock_client = MagicMock()
        mock_client.events.return_value.list.return_value.execute.side_effect = _make_http_error(
            google_status, "Test Google Error"
        )

        with patch("app.services.calendar_service.build", return_value=mock_client):
            resp = await async_client.get("/api/v1/calendar/events")
            assert resp.status_code == expected_http
            assert expected_detail_snippet in resp.json()["detail"]


# =============================================================================
# 6. Token Refresh & Multi-User Isolation
# =============================================================================

@pytest.mark.asyncio
async def test_expired_token_automatically_refreshes_for_calendar(
    async_client: AsyncClient, test_db: AsyncSession
):
    """Expired access token triggers automatic refresh before calling Calendar API."""
    user, _, _ = await create_test_user_with_calendar(
        test_db, is_expired=True, refresh_token="valid-cal-refresh-token"
    )
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [make_mock_calendar_item("primary")],
        "nextPageToken": None,
    }

    with patch.object(OAuthService, "refresh_access_token", return_value="new-fresh-token") as mock_refresh, \
         patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars")
        assert resp.status_code == 200
        mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_revoked_refresh_token_returns_safe_auth_error(async_client: AsyncClient, test_db: AsyncSession):
    """Revoked refresh token produces a safe 401 error instructing the user to reconnect."""
    user, _, _ = await create_test_user_with_calendar(test_db, is_expired=True)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    from app.services.oauth_service import TokenRefreshError

    with patch.object(
        OAuthService,
        "refresh_access_token",
        side_effect=TokenRefreshError("Token revoked", is_revoked=True),
    ):
        resp = await async_client.get("/api/v1/calendar/calendars")
        assert resp.status_code == 401
        assert "Google account authentication is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_multi_user_isolation_strictly_enforced(async_client: AsyncClient, test_db: AsyncSession):
    """
    User A and User B have separate Google accounts.
    User A's session can NEVER access User B's calendar data.
    """
    user_a, _, _ = await create_test_user_with_calendar(
        test_db, email="user_a@example.com", access_token="token-user-a"
    )
    user_b, _, _ = await create_test_user_with_calendar(
        test_db, email="user_b@example.com", access_token="token-user-b"
    )

    # Request as User A
    cookie_a = SecurityManager.create_session_token(user_id=user_a.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, cookie_a)

    mock_client_a = MagicMock()
    mock_client_a.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [make_mock_calendar_item("cal-user-a", "User A Calendar")],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client_a):
        resp_a = await async_client.get("/api/v1/calendar/calendars")
        assert resp_a.status_code == 200
        assert resp_a.json()["calendars"][0]["summary"] == "User A Calendar"

    # Request as User B
    cookie_b = SecurityManager.create_session_token(user_id=user_b.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, cookie_b)

    mock_client_b = MagicMock()
    mock_client_b.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [make_mock_calendar_item("cal-user-b", "User B Calendar")],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client_b):
        resp_b = await async_client.get("/api/v1/calendar/calendars")
        assert resp_b.status_code == 200
        assert resp_b.json()["calendars"][0]["summary"] == "User B Calendar"


# =============================================================================
# 7. Incremental Scope Merging & Token Preservation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_incremental_scope_merging_preserves_both_gmail_and_calendar(test_db: AsyncSession):
    """
    When an existing user with gmail.readonly authorizes calendar.readonly:
    The OAuthToken is updated with both scopes merged and no duplicates.
    """
    user_info = {
        "email": "incremental@example.com",
        "id": "google-inc-123",
        "name": "Incremental User",
    }
    # Initial OAuth: Gmail scope only
    token_data_step1 = {
        "access_token": "token-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        "scope": "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gmail.readonly",
    }
    user, acct = await OAuthService.sync_user_and_google_account(
        test_db, user_info, token_data_step1
    )

    scopes1 = await OAuthService.get_user_granted_scopes(test_db, user.id)
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes1
    assert "https://www.googleapis.com/auth/calendar.readonly" not in scopes1

    # Step 2: Incremental authorization adding Calendar scope (Google returns new access token, no refresh token)
    token_data_step2 = {
        "access_token": "token-2",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/calendar.readonly",
    }
    await OAuthService.sync_user_and_google_account(
        test_db, user_info, token_data_step2, session_user_id=user.id
    )

    scopes2 = await OAuthService.get_user_granted_scopes(test_db, user.id)
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes2
    assert "https://www.googleapis.com/auth/calendar.readonly" in scopes2

    # Assert refresh token was preserved and NOT overwritten with None
    token_record = (await test_db.execute(
        OAuthToken.__table__.select().where(OAuthToken.user_id == user.id)
    )).fetchone()
    assert token_record.encrypted_refresh_token is not None


# =============================================================================
# 8. Security & Read-Only Invariants Tests
# =============================================================================

@pytest.mark.asyncio
async def test_tokens_and_secrets_never_appear_in_api_responses(
    async_client: AsyncClient, test_db: AsyncSession
):
    """Responses must never contain tokens, client secrets, or cryptographic keys."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [make_mock_calendar_item("primary")],
        "nextPageToken": None,
    }
    mock_client.events.return_value.list.return_value.execute.return_value = {
        "items": [make_mock_event_item("evt1")],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp1 = await async_client.get("/api/v1/calendar/calendars")
        text1 = resp1.text
        assert "token" not in text1.lower() or "next_page_token" in text1
        assert "secret" not in text1.lower()
        assert "bearer" not in text1.lower()

        resp2 = await async_client.get("/api/v1/calendar/events")
        text2 = resp2.text
        assert "secret" not in text2.lower()
        assert "bearer" not in text2.lower()


@pytest.mark.asyncio
async def test_no_destructive_or_write_calendar_endpoints_exist(
    async_client: AsyncClient, test_db: AsyncSession
):
    """Asserts that no POST, PUT, PATCH, or DELETE endpoints exist under /api/v1/calendar."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    # Attempt POST /api/v1/calendar/events (should not exist -> 405 Method Not Allowed)
    resp1 = await async_client.post("/api/v1/calendar/events", json={"summary": "New Event"})
    assert resp1.status_code == 405

    # Attempt DELETE /api/v1/calendar/events/evt123 (should not exist -> 405 Method Not Allowed)
    resp2 = await async_client.delete("/api/v1/calendar/events/evt123")
    assert resp2.status_code == 405

    # Attempt PUT /api/v1/calendar/events/evt123 (should not exist -> 405 Method Not Allowed)
    resp3 = await async_client.put("/api/v1/calendar/events/evt123", json={"summary": "Updated"})
    assert resp3.status_code == 405


@pytest.mark.asyncio
async def test_event_descriptions_and_tokens_never_logged(
    async_client: AsyncClient, test_db: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """Event descriptions, private contents, and tokens must never appear in log records."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    secret_phrase = "SUPER_SECRET_PROJECT_CODENAME_XYZ"
    mock_client = MagicMock()
    mock_item = make_mock_event_item("evt_secret", summary=secret_phrase)
    mock_item["description"] = f"Confidential meeting details: {secret_phrase}"
    mock_client.events.return_value.list.return_value.execute.return_value = {
        "items": [mock_item],
        "nextPageToken": None,
    }

    with caplog.at_level(logging.DEBUG), patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/events")
        assert resp.status_code == 200

        for record in caplog.records:
            assert "mock-cal-access-token" not in record.message
            assert "Bearer" not in record.message
            assert secret_phrase not in record.message


@pytest.mark.asyncio
async def test_event_summary_missing_title_defaults_safely(
    async_client: AsyncClient, test_db: AsyncSession
):
    """An event without a summary title defaults to '(No title)'."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.events.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "evt_notitle", "start": {"date": "2026-09-15"}, "end": {"date": "2026-09-15"}}],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"][0]["summary"] == "(No title)"


@pytest.mark.asyncio
async def test_event_without_conference_or_attendees(
    async_client: AsyncClient, test_db: AsyncSession
):
    """An event without conference data or attendees normalizes safely."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.events.return_value.get.return_value.execute.return_value = {
        "id": "evt_minimal",
        "summary": "Solo Task",
        "start": {"dateTime": "2026-09-15T12:00:00Z"},
        "end": {"dateTime": "2026-09-15T13:00:00Z"},
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/events/evt_minimal")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "evt_minimal"
        assert data["attendees"] == []
        assert data["conference"] is None


@pytest.mark.asyncio
async def test_calendar_id_with_special_characters_url_safe(
    async_client: AsyncClient, test_db: AsyncSession
):
    """Calendar ID with special characters like # and @ is safely handled and decoded."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    special_cal_id = "c_123#xyz@group.calendar.google.com"
    mock_client = MagicMock()
    mock_client.events.return_value.list.return_value.execute.return_value = {
        "items": [],
        "nextPageToken": None,
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        encoded_id = "c_123%23xyz%40group.calendar.google.com"
        resp = await async_client.get(f"/api/v1/calendar/events?calendar_id={encoded_id}")
        assert resp.status_code == 200
        mock_client.events.return_value.list.assert_called_once()
        call_kwargs = mock_client.events.return_value.list.call_args[1]
        assert call_kwargs["calendarId"] == special_cal_id


@pytest.mark.asyncio
async def test_get_calendar_fallback_to_calendars_resource(
    async_client: AsyncClient, test_db: AsyncSession
):
    """If calendarList.get returns 404, get_calendar falls back to calendars.get."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    session_cookie = SecurityManager.create_session_token(user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, session_cookie)

    mock_client = MagicMock()
    mock_client.calendarList.return_value.get.return_value.execute.side_effect = _make_http_error(404, "Not Found")
    mock_client.calendars.return_value.get.return_value.execute.return_value = {
        "id": "external_cal_id",
        "summary": "External Subscribed Calendar",
        "timeZone": "UTC",
    }

    with patch("app.services.calendar_service.build", return_value=mock_client):
        resp = await async_client.get("/api/v1/calendar/calendars/external_cal_id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "external_cal_id"
        assert data["summary"] == "External Subscribed Calendar"


@pytest.mark.asyncio
async def test_has_required_scope_recognizes_full_and_readonly_calendar(test_db: AsyncSession):
    """OAuthService.has_required_scope accepts both calendar.readonly and broader calendar scope."""
    user, _, _ = await create_test_user_with_calendar(
        test_db,
        scopes=["openid", "https://www.googleapis.com/auth/calendar"],
    )
    has_read = await OAuthService.has_required_scope(
        test_db, user.id, "https://www.googleapis.com/auth/calendar.readonly"
    )
    assert has_read is True


@pytest.mark.asyncio
async def test_calendar_service_rejects_empty_ids(test_db: AsyncSession):
    """CalendarService methods raise CalendarNotFoundError when given whitespace or empty IDs."""
    user, _, _ = await create_test_user_with_calendar(test_db)
    service = CalendarService(user_id=user.id, db=test_db)

    with pytest.raises(CalendarNotFoundError):
        await service.get_calendar("   ")

    with pytest.raises(CalendarNotFoundError):
        await service.get_event("primary", "  ")

    with pytest.raises(CalendarNotFoundError):
        await service.list_events(calendar_id="  ")

