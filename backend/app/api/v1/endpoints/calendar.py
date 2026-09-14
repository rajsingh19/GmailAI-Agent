"""
Google Calendar API Endpoints.
Provides user-isolated, strictly read-only operations for Google Calendars and Events.
CRITICAL SECURITY:
- user_id is derived strictly from current_user.id (server-side session cookie).
- calendar_id alone is NOT an authorization boundary; requests use the authenticated user's credentials.
- Zero tokens or credentials in API responses.
- Explicit scope validation before calling Google APIs.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.calendar import (
    CalendarDetail,
    CalendarEventDetail,
    CalendarEventListResponse,
    CalendarListResponse,
)
from app.services.calendar_service import (
    CalendarAuthenticationError,
    CalendarCommunicationError,
    CalendarNotConnectedError,
    CalendarNotFoundError,
    CalendarPermissionError,
    CalendarRateLimitError,
    CalendarScopeMissingError,
    CalendarService,
    CalendarServiceError,
    CalendarValidationError,
)

router = APIRouter()


def _handle_service_exception(exc: Exception) -> HTTPException:
    """Maps Calendar service domain exceptions to standard HTTP error responses."""
    if isinstance(exc, CalendarNotConnectedError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No connected Google account found. Please connect your Google account.",
        )
    elif isinstance(exc, CalendarScopeMissingError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google Calendar access is not authorized. Please authorize Calendar access.",
        )
    elif isinstance(exc, CalendarAuthenticationError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account authentication is required. Please re-authenticate.",
        )
    elif isinstance(exc, CalendarPermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Calendar access is forbidden or unavailable for this account.",
        )
    elif isinstance(exc, CalendarNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar or event not found.",
        )
    elif isinstance(exc, CalendarValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    elif isinstance(exc, CalendarRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Google Calendar API rate limit reached. Please try again later.",
        )
    elif isinstance(exc, CalendarCommunicationError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to communicate with Google Calendar.",
        )
    elif isinstance(exc, CalendarServiceError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your Calendar request.",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error.",
    )


@router.get(
    "/calendars",
    response_model=CalendarListResponse,
    summary="List Accessible Calendars",
    description="Retrieves a list of all calendars accessible to the authenticated user.",
)
async def list_calendars(
    page_token: Optional[str] = Query(
        default=None,
        description="Pagination token for calendar list",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarListResponse:
    """Lists accessible calendars for the authenticated user."""
    service = CalendarService(user_id=current_user.id, db=db)
    try:
        return await service.get_calendar_list(page_token=page_token)
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.get(
    "/calendars/{calendar_id}",
    response_model=CalendarDetail,
    summary="Get Calendar Details",
    description="Retrieves metadata for a specific calendar ID.",
)
async def get_calendar_details(
    calendar_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarDetail:
    """Retrieves metadata for a specific calendar."""
    service = CalendarService(user_id=current_user.id, db=db)
    try:
        return await service.get_calendar(calendar_id=calendar_id)
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.get(
    "/events",
    response_model=CalendarEventListResponse,
    summary="List Calendar Events",
    description="Retrieves events for a specified calendar (defaults to primary) with date filtering and search.",
)
async def list_calendar_events(
    calendar_id: str = Query(
        default="primary",
        description="Calendar identifier (e.g. 'primary' or email address)",
    ),
    time_min: Optional[datetime] = Query(
        default=None,
        description="Lower bound (inclusive) for event end times (ISO 8601 / RFC 3339)",
    ),
    time_max: Optional[datetime] = Query(
        default=None,
        description="Upper bound (exclusive) for event start times (ISO 8601 / RFC 3339)",
    ),
    max_results: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of events to return (1-100, default 20)",
    ),
    page_token: Optional[str] = Query(
        default=None,
        description="Page token for fetching next page of events",
    ),
    query: Optional[str] = Query(
        default=None,
        description="Free text search query to filter events",
    ),
    single_events: bool = Query(
        default=True,
        description="Whether to expand recurring events into individual instances",
    ),
    order_by: Optional[str] = Query(
        default=None,
        description="Order by 'startTime' or 'updated' (startTime requires single_events=True)",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarEventListResponse:
    """Lists events strictly scoped to the authenticated user's credentials."""
    service = CalendarService(user_id=current_user.id, db=db)
    try:
        return await service.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            page_token=page_token,
            query=query,
            single_events=single_events,
            order_by=order_by,
        )
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.get(
    "/calendars/{calendar_id}/events/{event_id}",
    response_model=CalendarEventDetail,
    summary="Get Calendar Event Detail",
    description="Retrieves full details for a specific event on a calendar.",
)
async def get_calendar_event_detail(
    calendar_id: str,
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarEventDetail:
    """Retrieves full details for a specific event on a calendar."""
    service = CalendarService(user_id=current_user.id, db=db)
    try:
        return await service.get_event(calendar_id=calendar_id, event_id=event_id)
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.get(
    "/events/{event_id}",
    response_model=CalendarEventDetail,
    summary="Get Primary Calendar Event Detail",
    description="Convenience endpoint to retrieve an event from the user's primary calendar.",
)
async def get_primary_calendar_event_detail(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarEventDetail:
    """Convenience endpoint to retrieve an event from the user's primary calendar."""
    service = CalendarService(user_id=current_user.id, db=db)
    try:
        return await service.get_event(calendar_id="primary", event_id=event_id)
    except Exception as exc:
        raise _handle_service_exception(exc) from exc
