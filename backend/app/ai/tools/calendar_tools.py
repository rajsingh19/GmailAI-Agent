import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolDefinition, ToolRegistry, RiskLevel
from app.services.calendar_service import (
    CalendarService,
    CalendarNotConnectedError,
    CalendarScopeMissingError,
    CalendarAuthenticationError,
    CalendarNotFoundError,
    CalendarServiceError,
)

logger = logging.getLogger(__name__)


async def execute_list_calendars(
    user_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Tool to list user Google Calendars."""
    service = CalendarService(user_id=user_id, db=db)
    try:
        resp = await service.get_calendar_list()
        cals = [
            {
                "id": c.id,
                "summary": c.summary,
                "primary": c.primary,
                "time_zone": c.time_zone,
            }
            for c in resp.calendars
        ]
        return {
            "source": "calendar",
            "trusted": False,
            "status": "success",
            "count": len(cals),
            "calendars": cals,
        }
    except CalendarNotConnectedError:
        return {"source": "calendar", "trusted": False, "status": "error", "message": "Google account is not connected."}
    except CalendarScopeMissingError:
        return {"source": "calendar", "trusted": False, "status": "error", "message": "Google Calendar scope is missing. Please connect Calendar access."}
    except (CalendarAuthenticationError, CalendarServiceError) as exc:
        return {"source": "calendar", "trusted": False, "status": "error", "message": str(exc)}
    except Exception as exc:
        return {"source": "calendar", "trusted": False, "status": "error", "message": f"Failed to list calendars: {exc}"}


async def execute_get_calendar(
    user_id: str,
    db: AsyncSession,
    calendar_id: str = "primary",
) -> Dict[str, Any]:
    """Tool to get details of a calendar."""
    service = CalendarService(user_id=user_id, db=db)
    try:
        cal = await service.get_calendar(calendar_id=calendar_id)
        return {
            "source": "calendar",
            "trusted": False,
            "status": "success",
            "calendar": {
                "id": cal.id,
                "summary": cal.summary,
                "primary": cal.primary,
                "time_zone": cal.time_zone,
            },
        }
    except Exception as exc:
        return {"source": "calendar", "trusted": False, "status": "error", "message": str(exc)}


async def execute_list_calendar_events(
    user_id: str,
    db: AsyncSession,
    calendar_id: Optional[str] = "primary",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
    max_results: Optional[int] = 10,
) -> Dict[str, Any]:
    """Tool to list or search upcoming/scheduled calendar events."""
    lim = min(max(max_results or 10, 1), 20)
    service = CalendarService(user_id=user_id, db=db)
    try:
        resp = await service.list_events(
            calendar_id=calendar_id or "primary",
            time_min=time_min,
            time_max=time_max,
            query=query,
            max_results=lim,
            single_events=True,
        )
        events = [
            {
                "id": e.id,
                "summary": e.summary,
                "start": e.start,
                "end": e.end,
                "is_all_day": e.is_all_day,
                "location": e.location,
                "meet_link": e.conference_uri,
                "attendees_count": e.attendees_count,
            }
            for e in resp.events
        ]
        return {
            "source": "calendar",
            "trusted": False,
            "status": "success",
            "calendar_id": calendar_id or "primary",
            "count": len(events),
            "events": events,
        }
    except CalendarNotConnectedError:
        return {"source": "calendar", "trusted": False, "status": "error", "message": "Google account is not connected."}
    except CalendarScopeMissingError:
        return {"source": "calendar", "trusted": False, "status": "error", "message": "Google Calendar scope is missing."}
    except (CalendarAuthenticationError, CalendarServiceError) as exc:
        return {"source": "calendar", "trusted": False, "status": "error", "message": str(exc)}
    except Exception as exc:
        return {"source": "calendar", "trusted": False, "status": "error", "message": f"Failed to list events: {exc}"}


async def execute_get_calendar_event(
    user_id: str,
    db: AsyncSession,
    event_id: str,
    calendar_id: Optional[str] = "primary",
) -> Dict[str, Any]:
    """Tool to retrieve full details of a specific calendar event."""
    service = CalendarService(user_id=user_id, db=db)
    try:
        event = await service.get_event(calendar_id=calendar_id or "primary", event_id=event_id)

        desc = event.description or ""
        if len(desc) > 1000:
            desc = desc[:1000] + "... [TRUNCATED]"

        attendees = [
            {"email": a.email, "name": a.display_name, "status": a.response_status}
            for a in event.attendees[:10]
        ]

        meet_uri = event.conference.uri if event.conference else None

        return {
            "source": "calendar",
            "trusted": False,
            "status": "success",
            "event": {
                "id": event.id,
                "summary": event.summary,
                "description": desc,
                "start": event.start,
                "end": event.end,
                "location": event.location,
                "meet_link": meet_uri,
                "attendees": attendees,
                "is_all_day": event.is_all_day,
            },
        }
    except CalendarNotFoundError:
        return {"source": "calendar", "trusted": False, "status": "error", "message": f"Event '{event_id}' not found."}
    except Exception as exc:
        return {"source": "calendar", "trusted": False, "status": "error", "message": str(exc)}


def register_calendar_tools() -> None:
    """Registers all read-only Calendar tools into ToolRegistry."""
    ToolRegistry.register(
        ToolDefinition(
            name="list_calendars",
            description="List all available Google Calendars for the user.",
            friendly_name="Listing calendars",
            risk_level=RiskLevel.READ,
            func=execute_list_calendars,
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="get_calendar",
            description="Get metadata of a specific calendar by ID (or 'primary').",
            friendly_name="Fetching calendar",
            risk_level=RiskLevel.READ,
            func=execute_get_calendar,
            parameters_schema={
                "type": "object",
                "properties": {
                    "calendar_id": {"type": "string", "description": "Calendar ID, defaults to 'primary'"},
                },
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="list_calendar_events",
            description="List or search calendar events within a time range (time_min, time_max in ISO 8601) or query string.",
            friendly_name="Checking calendar events",
            risk_level=RiskLevel.READ,
            func=execute_list_calendar_events,
            parameters_schema={
                "type": "object",
                "properties": {
                    "calendar_id": {"type": "string", "description": "Calendar ID, defaults to 'primary'"},
                    "time_min": {"type": "string", "description": "Start of time range (ISO 8601, e.g. '2026-09-15T00:00:00Z')"},
                    "time_max": {"type": "string", "description": "End of time range (ISO 8601, e.g. '2026-09-16T23:59:59Z')"},
                    "query": {"type": "string", "description": "Free text search term filter"},
                    "max_results": {"type": "integer", "description": "Max events to return (default 10, max 20)"},
                },
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="get_calendar_event",
            description="Retrieve detailed information about a specific calendar event including description, attendees, and Meet link.",
            friendly_name="Fetching event details",
            risk_level=RiskLevel.READ,
            func=execute_get_calendar_event,
            parameters_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Unique Google Calendar Event ID"},
                    "calendar_id": {"type": "string", "description": "Calendar ID, defaults to 'primary'"},
                },
                "required": ["event_id"],
            },
        )
    )
