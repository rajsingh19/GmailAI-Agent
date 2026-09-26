"""
Google Calendar Service.
Handles all interactions with the Google Calendar API (v3).
Enforces:
- Strict multi-user isolation (scoped to authenticated user_id).
- Explicit scope verification (calendar.readonly) before any API call.
- Safe token retrieval and automatic token refresh via OAuthService.
- RFC3339 timezone-aware datetime handling and all-day event distinction.
- Sanitized logging (zero token, credential, attendee list, or event body leakage).
- STRICT READ-ONLY OPERATIONS (no event creation, modification, or deletion).
"""
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.parse

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.resilience import retry_with_backoff
from app.schemas.calendar import (
    CalendarAttendee,
    CalendarConferenceData,
    CalendarDetail,
    CalendarEventDetail,
    CalendarEventListResponse,
    CalendarEventSummary,
    CalendarListResponse,
    CalendarReminder,
    CalendarSummary,
)
from app.services.oauth_service import OAuthError, OAuthService, TokenRefreshError


# =============================================================================
# Domain Exceptions
# =============================================================================

class CalendarServiceError(Exception):
    """Base exception for Calendar service errors."""
    pass


class CalendarNotConnectedError(CalendarServiceError):
    """Raised when the user has not connected a Google account."""
    pass


class CalendarScopeMissingError(CalendarServiceError):
    """Raised when Google account is connected but calendar.readonly scope is missing."""
    pass


class CalendarAuthenticationError(CalendarServiceError):
    """Raised when Google account authentication is required, expired, or revoked."""
    pass


class CalendarPermissionError(CalendarServiceError):
    """Raised when Calendar access is forbidden."""
    pass


class CalendarNotFoundError(CalendarServiceError):
    """Raised when the requested calendar or event is not found."""
    pass


class CalendarValidationError(CalendarServiceError):
    """Raised when calendar query parameters (e.g. time range) are invalid."""
    pass


class CalendarRateLimitError(CalendarServiceError):
    """Raised when Google Calendar API rate limits are encountered."""
    pass


class CalendarCommunicationError(CalendarServiceError):
    """Raised when a network or server error occurs communicating with Google Calendar."""
    pass


# =============================================================================
# Helper Utilities
# =============================================================================

def format_rfc3339(dt: Optional[datetime]) -> Optional[str]:
    """Formats a datetime object to RFC3339 string with timezone offset (e.g. 2026-09-15T09:00:00+05:30 or Z)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Fallback to UTC if naive
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# =============================================================================
# Calendar Service Implementation
# =============================================================================

class CalendarService:
    """Encapsulates all Google Calendar API read operations for an authenticated user."""

    REQUIRED_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

    def __init__(self, user_id: str, db: AsyncSession) -> None:
        self.user_id = user_id
        self.db = db

    async def _get_client(self) -> Any:
        """
        Validates the user's connection and granted scopes, retrieves a valid access token,
        and builds a Google Calendar v3 Resource client.
        """
        # 1. Verify Google Account and Calendar Scope
        has_scope = await OAuthService.has_required_scope(self.db, self.user_id, self.REQUIRED_SCOPE)
        if not has_scope:
            # Check if user has an account at all
            status_data = await OAuthService.get_connection_status(self.db, self.user_id)
            if not status_data.get("connected"):
                logger.info("No connected Google account for user_id=%s", self.user_id)
                raise CalendarNotConnectedError("Google account is not connected.")
            logger.warning("User %s connected but missing calendar.readonly scope", self.user_id)
            raise CalendarScopeMissingError(
                "Google Calendar access is not authorized. Please authorize Calendar access."
            )

        # 2. Retrieve valid access token (auto-refreshes if needed)
        try:
            access_token = await OAuthService.get_valid_access_token(self.db, self.user_id)
        except TokenRefreshError as exc:
            logger.warning("Token refresh failed for user_id=%s (revoked=%s)", self.user_id, exc.is_revoked)
            raise CalendarAuthenticationError(
                "Google account authorization expired or was revoked. Please reconnect."
            ) from exc
        except OAuthError as exc:
            raise CalendarNotConnectedError("Google account is not connected.") from exc

        credentials = Credentials(token=access_token)
        return await asyncio.to_thread(
            build, "calendar", "v3", credentials=credentials, cache_discovery=False
        )

    async def get_calendar_list(self, page_token: Optional[str] = None) -> CalendarListResponse:
        """
        Retrieves the list of calendars accessible to the user (e.g. primary, subscribed).
        """
        client = await self._get_client()

        params: Dict[str, Any] = {"minAccessRole": "reader"}
        if page_token:
            params["pageToken"] = page_token

        def _fetch():
            return client.calendarList().list(**params).execute()

        try:
            data = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch),
                operation_name="get_calendar_list",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation="get_calendar_list")
        except Exception as exc:
            logger.error("Unexpected error fetching calendar list for user_id=%s: %s", self.user_id, type(exc).__name__)
            raise CalendarCommunicationError("Unable to communicate with Google Calendar.") from exc

        items = data.get("items", []) or []
        calendars: List[CalendarSummary] = []
        for item in items:
            calendars.append(
                CalendarSummary(
                    id=item.get("id", ""),
                    summary=item.get("summary", "(Untitled Calendar)"),
                    description=item.get("description"),
                    time_zone=item.get("timeZone"),
                    primary=bool(item.get("primary", False)),
                    background_color=item.get("backgroundColor"),
                    access_role=item.get("accessRole"),
                    selected=bool(item.get("selected", False)),
                    hidden=bool(item.get("hidden", False)),
                )
            )

        logger.info("Retrieved %d calendars for user_id=%s", len(calendars), self.user_id)
        return CalendarListResponse(
            calendars=calendars,
            next_page_token=data.get("nextPageToken"),
        )

    async def get_calendar(self, calendar_id: str) -> CalendarDetail:
        """
        Retrieves detailed metadata for a specific calendar.
        """
        if not calendar_id or not calendar_id.strip():
            raise CalendarNotFoundError("Invalid or empty calendar ID.")

        clean_id = calendar_id.strip()
        client = await self._get_client()

        def _fetch():
            try:
                return client.calendarList().get(calendarId=clean_id).execute()
            except HttpError as err:
                if err.resp.status == 404:
                    return client.calendars().get(calendarId=clean_id).execute()
                raise

        try:
            item = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch),
                operation_name=f"get_calendar({clean_id})",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation=f"get_calendar({clean_id})")
        except Exception as exc:
            logger.error("Unexpected error fetching calendar %s for user_id=%s: %s", clean_id, self.user_id, type(exc).__name__)
            raise CalendarCommunicationError("Unable to communicate with Google Calendar.") from exc

        return CalendarDetail(
            id=item.get("id", clean_id),
            summary=item.get("summary", "(Untitled Calendar)"),
            description=item.get("description"),
            location=item.get("location"),
            time_zone=item.get("timeZone"),
            primary=bool(item.get("primary", False)),
            access_role=item.get("accessRole"),
            selected=bool(item.get("selected", False)),
            hidden=bool(item.get("hidden", False)),
        )

    async def list_events(
        self,
        calendar_id: str = "primary",
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 20,
        page_token: Optional[str] = None,
        query: Optional[str] = None,
        single_events: bool = True,
        order_by: Optional[str] = None,
    ) -> CalendarEventListResponse:
        """
        Lists events for a specified calendar with date range filtering and query search.
        Expands recurring events by default with single_events=True.
        """
        if not calendar_id or not calendar_id.strip():
            raise CalendarNotFoundError("Invalid or empty calendar ID.")

        clean_cal_id = calendar_id.strip()
        bounded_max = max(1, min(max_results, 100))

        # Support both datetime and ISO string inputs
        if isinstance(time_min, str):
            try:
                time_min = datetime.fromisoformat(time_min.replace("Z", "+00:00"))
            except Exception:
                time_min = None

        if isinstance(time_max, str):
            try:
                time_max = datetime.fromisoformat(time_max.replace("Z", "+00:00"))
            except Exception:
                time_max = None

        # Validate date range order
        if time_min and time_max:
            t_min = time_min.replace(tzinfo=timezone.utc) if time_min.tzinfo is None else time_min
            t_max = time_max.replace(tzinfo=timezone.utc) if time_max.tzinfo is None else time_max
            if t_min > t_max:
                raise CalendarValidationError("time_min cannot be later than time_max.")

        client = await self._get_client()

        params: Dict[str, Any] = {
            "calendarId": clean_cal_id,
            "maxResults": bounded_max,
            "singleEvents": single_events,
        }
        if single_events:
            params["orderBy"] = order_by or "startTime"
        elif order_by:
            params["orderBy"] = order_by

        if time_min:
            params["timeMin"] = format_rfc3339(time_min)
        if time_max:
            params["timeMax"] = format_rfc3339(time_max)
        if page_token:
            params["pageToken"] = page_token
        if query:
            params["q"] = query

        def _fetch():
            return client.events().list(**params).execute()

        try:
            data = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch),
                operation_name=f"list_events({clean_cal_id})",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation=f"list_events({clean_cal_id})")
        except Exception as exc:
            logger.error("Unexpected error listing events for user_id=%s, cal=%s: %s", self.user_id, clean_cal_id, type(exc).__name__)
            raise CalendarCommunicationError("Unable to communicate with Google Calendar.") from exc

        raw_items = data.get("items", []) or []
        events: List[CalendarEventSummary] = []
        seen_ids = set()

        for item in raw_items:
            summary = self._normalize_event_summary(item, clean_cal_id)
            if summary and summary.id not in seen_ids:
                seen_ids.add(summary.id)
                events.append(summary)

        logger.info(
            "Retrieved %d events for user_id=%s on calendar=%s",
            len(events),
            self.user_id,
            clean_cal_id,
        )

        return CalendarEventListResponse(
            events=events,
            next_page_token=data.get("nextPageToken"),
            calendar_id=clean_cal_id,
        )

    async def get_event(self, calendar_id: str, event_id: str) -> CalendarEventDetail:
        """
        Retrieves full details for a specific calendar event.
        """
        if not calendar_id or not calendar_id.strip():
            raise CalendarNotFoundError("Invalid calendar ID.")
        if not event_id or not event_id.strip():
            raise CalendarNotFoundError("Invalid event ID.")

        clean_cal_id = calendar_id.strip()
        clean_event_id = event_id.strip()
        client = await self._get_client()

        def _fetch():
            return client.events().get(calendarId=clean_cal_id, eventId=clean_event_id).execute()

        try:
            item = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch),
                operation_name=f"get_event({clean_cal_id}, {clean_event_id})",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation=f"get_event({clean_cal_id}, {clean_event_id})")
        except Exception as exc:
            logger.error("Unexpected error fetching event %s for user_id=%s: %s", clean_event_id, self.user_id, type(exc).__name__)
            raise CalendarCommunicationError("Unable to communicate with Google Calendar.") from exc

        return self._normalize_event_detail(item, clean_cal_id)

    # =========================================================================
    # Internal Normalization Helpers
    # =========================================================================

    def _normalize_event_summary(self, item: Dict[str, Any], calendar_id: str) -> Optional[CalendarEventSummary]:
        """Normalizes raw Google event object into safe CalendarEventSummary."""
        event_id = item.get("id")
        if not event_id:
            return None

        # Determine start/end times and all-day status
        start_obj = item.get("start", {})
        end_obj = item.get("end", {})

        is_all_day = "date" in start_obj and "dateTime" not in start_obj
        start_val = start_obj.get("dateTime") or start_obj.get("date", "")
        end_val = end_obj.get("dateTime") or end_obj.get("date", "")

        # Time zone
        tz = start_obj.get("timeZone") or item.get("timeZone")

        # Conference information
        conf_data = item.get("conferenceData", {})
        entry_points = conf_data.get("entryPoints", []) or []
        video_entry = next((ep for ep in entry_points if ep.get("entryPointType") == "video"), None)
        has_conf = bool(video_entry or conf_data.get("conferenceId") or item.get("hangoutLink"))
        conf_uri = (
            video_entry.get("uri")
            if video_entry
            else item.get("hangoutLink")
        )

        # Attendees count
        attendees = item.get("attendees", []) or []

        # Organizer
        organizer = item.get("organizer", {}).get("displayName") or item.get("organizer", {}).get("email")

        return CalendarEventSummary(
            id=event_id,
            calendar_id=calendar_id,
            summary=item.get("summary") or "(No title)",
            description=item.get("description"),
            location=item.get("location"),
            start=str(start_val),
            end=str(end_val),
            time_zone=tz,
            status=item.get("status", "confirmed"),
            html_link=item.get("htmlLink"),
            organizer=organizer,
            attendees_count=len(attendees),
            is_all_day=is_all_day,
            has_conference=has_conf,
            conference_uri=conf_uri,
        )

    def _normalize_event_detail(self, item: Dict[str, Any], calendar_id: str) -> CalendarEventDetail:
        """Normalizes raw Google event object into full CalendarEventDetail."""
        event_id = item.get("id", "")
        start_obj = item.get("start", {})
        end_obj = item.get("end", {})

        is_all_day = "date" in start_obj and "dateTime" not in start_obj
        start_val = start_obj.get("dateTime") or start_obj.get("date", "")
        end_val = end_obj.get("dateTime") or end_obj.get("date", "")
        tz = start_obj.get("timeZone") or item.get("timeZone")

        # Normalize Attendees
        raw_attendees = item.get("attendees", []) or []
        attendees: List[CalendarAttendee] = []
        for att in raw_attendees:
            attendees.append(
                CalendarAttendee(
                    email=att.get("email"),
                    display_name=att.get("displayName"),
                    response_status=att.get("responseStatus"),
                    organizer=bool(att.get("organizer", False)),
                    self=bool(att.get("self", False)),
                )
            )

        # Normalize Conference Data
        conf_detail: Optional[CalendarConferenceData] = None
        conf_data = item.get("conferenceData", {})
        entry_points = conf_data.get("entryPoints", []) or []
        video_entry = next((ep for ep in entry_points if ep.get("entryPointType") == "video"), None)
        if video_entry or item.get("hangoutLink"):
            uri = video_entry.get("uri") if video_entry else item.get("hangoutLink")
            label = video_entry.get("label") if video_entry else None
            sol_name = conf_data.get("conferenceSolution", {}).get("name", "Google Meet")
            conf_detail = CalendarConferenceData(
                entry_point_type="video",
                uri=uri,
                label=label,
                solution_name=sol_name,
            )

        # Normalize Reminders
        reminders_obj = item.get("reminders", {})
        reminders = CalendarReminder(
            use_default=bool(reminders_obj.get("useDefault", True)),
            overrides=reminders_obj.get("overrides", []) or [],
        )

        return CalendarEventDetail(
            id=event_id,
            calendar_id=calendar_id,
            summary=item.get("summary") or "(No title)",
            description=item.get("description"),
            location=item.get("location"),
            start=str(start_val),
            end=str(end_val),
            time_zone=tz,
            status=item.get("status", "confirmed"),
            html_link=item.get("htmlLink"),
            organizer=item.get("organizer", {}).get("displayName") or item.get("organizer", {}).get("email"),
            creator=item.get("creator", {}).get("displayName") or item.get("creator", {}).get("email"),
            attendees=attendees,
            conference=conf_detail,
            reminders=reminders,
            recurrence=item.get("recurrence", []) or [],
            is_all_day=is_all_day,
        )

    def _handle_http_error(self, exc: HttpError, operation: str) -> None:
        """Translates Google HttpError into clean domain exceptions without leaking secrets."""
        status_code = exc.resp.status if hasattr(exc, "resp") and hasattr(exc.resp, "status") else 500

        logger.warning(
            "Calendar API HttpError during %s for user_id=%s (HTTP %d)",
            operation,
            self.user_id,
            status_code,
        )

        if status_code == 401:
            raise CalendarAuthenticationError("Google account authentication is required.")
        elif status_code == 403:
            raise CalendarPermissionError("Calendar access is forbidden or not available for this account.")
        elif status_code == 404:
            raise CalendarNotFoundError("Calendar or event not found.")
        elif status_code == 429:
            raise CalendarRateLimitError("Google Calendar API rate limit reached. Please try again later.")
        elif status_code >= 500:
            raise CalendarCommunicationError("Unable to communicate with Google Calendar.")
        else:
            raise CalendarCommunicationError(f"Google Calendar API error (HTTP {status_code}).")
