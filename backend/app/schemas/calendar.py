"""
Pydantic Schemas for Google Calendar API Integration.
Normalizes calendar and event metadata into clean, safe application-level models.
Guarantees:
- Zero raw Google internal tokens or secrets.
- Timezone preservation and explicit all-day indicator.
- Sanitized conference and attendee metadata.
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CalendarSummary(BaseModel):
    """Normalized summary of a Google Calendar."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Unique calendar identifier (e.g. 'primary' or email address)")
    summary: str = Field(description="Title / display name of the calendar")
    description: Optional[str] = Field(default=None, description="Optional description of the calendar")
    time_zone: Optional[str] = Field(default=None, description="IANA time zone database identifier")
    primary: bool = Field(default=False, description="True if this is the user's primary calendar")
    background_color: Optional[str] = Field(default=None, description="Hex color code for calendar display")
    access_role: Optional[str] = Field(default=None, description="User access level (e.g. 'owner', 'reader')")
    selected: bool = Field(default=False, description="Whether the calendar is selected in the UI")
    hidden: bool = Field(default=False, description="Whether the calendar is hidden")


class CalendarListResponse(BaseModel):
    """Response model for listing user's accessible calendars."""
    model_config = ConfigDict(from_attributes=True)

    calendars: List[CalendarSummary] = Field(default_factory=list)
    next_page_token: Optional[str] = Field(default=None, description="Pagination token")


class CalendarDetail(BaseModel):
    """Detailed metadata for a single Google Calendar."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Calendar ID")
    summary: str = Field(description="Calendar title")
    description: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None)
    time_zone: Optional[str] = Field(default=None)
    primary: bool = Field(default=False)
    access_role: Optional[str] = Field(default=None)
    selected: bool = Field(default=False)
    hidden: bool = Field(default=False)


class CalendarAttendee(BaseModel):
    """Safe normalized representation of a calendar event attendee."""
    model_config = ConfigDict(from_attributes=True)

    email: Optional[str] = Field(default=None, description="Attendee email address")
    display_name: Optional[str] = Field(default=None, description="Attendee display name")
    response_status: Optional[str] = Field(default=None, description="Status: 'accepted', 'declined', 'tentative', 'needsAction'")
    organizer: bool = Field(default=False, description="True if this attendee is the organizer")
    self: bool = Field(default=False, description="True if this attendee is the authenticated user")


class CalendarConferenceData(BaseModel):
    """Safe metadata for meeting / conference solutions (e.g. Google Meet)."""
    model_config = ConfigDict(from_attributes=True)

    entry_point_type: Optional[str] = Field(default=None, description="Type of entry point (video, phone)")
    uri: Optional[str] = Field(default=None, description="Join URI / URL")
    label: Optional[str] = Field(default=None, description="Display label for the meeting link")
    solution_name: Optional[str] = Field(default=None, description="Solution name (e.g. Google Meet)")


class CalendarReminder(BaseModel):
    """Reminder configuration for a calendar event."""
    model_config = ConfigDict(from_attributes=True)

    use_default: bool = Field(default=True)
    overrides: List[Dict[str, Any]] = Field(default_factory=list)


class CalendarEventSummary(BaseModel):
    """Lightweight summary of a calendar event for listing views."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Event identifier")
    calendar_id: str = Field(default="primary", description="Parent calendar ID")
    summary: str = Field(default="(No title)", description="Event summary / title")
    description: Optional[str] = Field(default=None, description="Plain text snippet or preview")
    location: Optional[str] = Field(default=None, description="Event location or room")
    start: str = Field(description="Start time (RFC3339 datetime or YYYY-MM-DD date)")
    end: str = Field(description="End time (RFC3339 datetime or YYYY-MM-DD date)")
    time_zone: Optional[str] = Field(default=None, description="Event time zone")
    status: Optional[str] = Field(default="confirmed", description="Status: 'confirmed', 'tentative', 'cancelled'")
    html_link: Optional[str] = Field(default=None, description="Web link to Google Calendar UI")
    organizer: Optional[str] = Field(default=None, description="Organizer display name or email")
    attendees_count: int = Field(default=0, description="Total number of attendees")
    is_all_day: bool = Field(default=False, description="True for all-day events")
    has_conference: bool = Field(default=False, description="True if event has Google Meet / video link")
    conference_uri: Optional[str] = Field(default=None, description="Direct meeting join URL")


class CalendarEventDetail(BaseModel):
    """Full detail of a specific calendar event."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Event identifier")
    calendar_id: str = Field(default="primary", description="Parent calendar ID")
    summary: str = Field(default="(No title)", description="Event summary / title")
    description: Optional[str] = Field(default=None, description="Full plain text description")
    location: Optional[str] = Field(default=None, description="Event location or room")
    start: str = Field(description="Start time (RFC3339 datetime or YYYY-MM-DD date)")
    end: str = Field(description="End time (RFC3339 datetime or YYYY-MM-DD date)")
    time_zone: Optional[str] = Field(default=None, description="Event time zone")
    status: Optional[str] = Field(default="confirmed", description="Status: 'confirmed', 'tentative', 'cancelled'")
    html_link: Optional[str] = Field(default=None, description="Web link to Google Calendar UI")
    organizer: Optional[str] = Field(default=None, description="Organizer display name or email")
    creator: Optional[str] = Field(default=None, description="Creator display name or email")
    attendees: List[CalendarAttendee] = Field(default_factory=list, description="List of normalized attendees")
    conference: Optional[CalendarConferenceData] = Field(default=None, description="Conference / Meet details")
    reminders: Optional[CalendarReminder] = Field(default=None, description="Reminder preferences")
    recurrence: List[str] = Field(default_factory=list, description="RRULE recurrence specifications")
    is_all_day: bool = Field(default=False, description="True for all-day events")


class CalendarEventListResponse(BaseModel):
    """Response model for listing calendar events."""
    model_config = ConfigDict(from_attributes=True)

    events: List[CalendarEventSummary] = Field(default_factory=list)
    next_page_token: Optional[str] = Field(default=None, description="Pagination token")
    calendar_id: str = Field(default="primary")
