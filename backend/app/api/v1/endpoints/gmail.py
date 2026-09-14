"""
Gmail API Endpoints.
Provides user-isolated read operations for Gmail profile and messages.
CRITICAL SECURITY:
- user_id is strictly derived from the authenticated session (current_user.id).
- Frontend cannot request data for any other user.
- Zero credentials or tokens in API responses.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.gmail import (
    GmailMessageDetail,
    GmailMessageListResponse,
    GmailProfileResponse,
)
from app.services.gmail_service import (
    GmailAuthenticationError,
    GmailCommunicationError,
    GmailNotConnectedError,
    GmailNotFoundError,
    GmailPermissionError,
    GmailRateLimitError,
    GmailService,
    GmailServiceError,
)

router = APIRouter()


def _handle_service_exception(exc: Exception) -> HTTPException:
    """Maps Gmail service domain exceptions to standard HTTP error responses."""
    if isinstance(exc, GmailNotConnectedError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No connected Google account found. Please connect your Google account.",
        )
    elif isinstance(exc, GmailAuthenticationError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account authentication is required. Please re-authenticate.",
        )
    elif isinstance(exc, GmailPermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Gmail access is not available for this account.",
        )
    elif isinstance(exc, GmailNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email message not found.",
        )
    elif isinstance(exc, GmailRateLimitError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Gmail API rate limit reached. Please try again later.",
        )
    elif isinstance(exc, GmailCommunicationError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to communicate with Gmail.",
        )
    elif isinstance(exc, GmailServiceError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your Gmail request.",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error.",
    )


@router.get(
    "/profile",
    response_model=GmailProfileResponse,
    summary="Get Gmail Profile",
    description="Retrieves basic statistics (total messages, threads) and address for the connected Gmail account.",
)
async def get_gmail_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailProfileResponse:
    """Retrieves safe profile metrics for the authenticated user's Google account."""
    service = GmailService(user_id=current_user.id, db=db)
    try:
        return await service.get_profile()
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.get(
    "/messages",
    response_model=GmailMessageListResponse,
    summary="List Gmail Messages",
    description="Retrieves a paginated list of email summaries. Supports standard Gmail query syntax (e.g. is:unread).",
)
async def list_gmail_messages(
    max_results: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of messages to return (1-100, default 20)",
    ),
    page_token: Optional[str] = Query(
        default=None,
        description="Page token for fetching next page of messages",
    ),
    query: Optional[str] = Query(
        default=None,
        description="Optional Gmail search query (e.g., 'is:unread', 'from:john@example.com', 'subject:meeting')",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailMessageListResponse:
    """Lists message summaries strictly scoped to the authenticated user's connected account."""
    service = GmailService(user_id=current_user.id, db=db)
    try:
        return await service.list_messages(
            max_results=max_results,
            page_token=page_token,
            query=query,
        )
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.get(
    "/messages/{message_id}",
    response_model=GmailMessageDetail,
    summary="Get Gmail Message Details",
    description="Retrieves full email details, normalized plain text, sanitized HTML text, and attachment metadata.",
)
async def get_gmail_message_detail(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailMessageDetail:
    """Retrieves full details for a specific email message."""
    service = GmailService(user_id=current_user.id, db=db)
    try:
        return await service.get_message(message_id=message_id)
    except Exception as exc:
        raise _handle_service_exception(exc) from exc
