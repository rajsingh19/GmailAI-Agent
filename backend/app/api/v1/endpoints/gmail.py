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
    GmailReplyDraftRequest,
    GmailReplyDraftSaveRequest,
    GmailReplyDraftResponse,
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
from app.services.smart_reply_service import SmartReplyService
from app.ai.providers.base import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMDailyQuotaExhaustedError,
    LLMServiceUnavailableError,
    LLMTimeoutError,
    LLMProviderError,
)

router = APIRouter()


def _handle_service_exception(exc: Exception) -> HTTPException:
    """Maps Gmail and Smart Reply service domain exceptions to standard HTTP error responses."""
    if isinstance(exc, HTTPException):
        return exc
    elif isinstance(exc, GmailNotConnectedError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No connected Google account found. Please connect your Google account.",
        )
    elif isinstance(exc, GmailAuthenticationError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account authentication is required. Please re-authenticate.",
        )
    elif isinstance(exc, LLMAuthenticationError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AI service authentication is required or credentials expired.",
        )
    elif isinstance(exc, GmailPermissionError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "Gmail permission is not authorized for this account.",
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
    elif isinstance(exc, LLMDailyQuotaExhaustedError) or getattr(exc, "is_daily_quota", False):
        headers = {"X-Quota-Exhausted": "daily"}
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Gemini daily quota exhausted. Smart Reply will work when your quota resets or you configure a billing-enabled plan.",
            headers=headers,
        )
    elif isinstance(exc, LLMRateLimitError):
        retry_after = getattr(exc, "retry_after", None)
        retry_secs = int(retry_after) if retry_after is not None and retry_after > 0 else 30
        headers = {"Retry-After": str(retry_secs)}
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"The AI service is temporarily busy (rate limit reached). Please try again in ~{retry_secs} seconds.",
            headers=headers,
        )
    elif isinstance(exc, LLMTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI service timed out while generating reply draft. Please try again.",
        )
    elif isinstance(exc, GmailCommunicationError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to communicate with Gmail.",
        )
    elif isinstance(exc, LLMServiceUnavailableError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to communicate with AI service.",
        )
    elif isinstance(exc, GmailServiceError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your Gmail request.",
        )
    elif isinstance(exc, LLMProviderError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while generating reply draft.",
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


@router.post(
    "/messages/{message_id}/reply-draft",
    response_model=GmailReplyDraftResponse,
    summary="Generate Smart Reply Draft",
    description="Generates an on-demand, context-aware smart reply draft for a specific email message using Gemini.",
)
async def generate_smart_reply_draft(
    message_id: str,
    payload: Optional[GmailReplyDraftRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailReplyDraftResponse:
    """
    Generates a personalized, context-aware smart reply draft for the specified email.
    Operates strictly on-demand when the user clicks 'Generate Reply'.
    Auto-persists the draft in cloud storage for cross-device synchronization.
    Never sends emails or saves drafts to Gmail automatically.
    """
    request_data = payload or GmailReplyDraftRequest()
    service = SmartReplyService(user_id=current_user.id, db=db)
    try:
        return await service.generate_reply_draft(
            message_id=message_id,
            tone=request_data.tone or "professional",
            custom_instructions=request_data.custom_instructions,
            include_thread_context=request_data.include_thread_context,
        )
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.get(
    "/messages/{message_id}/reply-draft",
    response_model=GmailReplyDraftResponse,
    summary="Get Saved Smart Reply Draft",
    description="Retrieves a persisted reply draft for the specified email message, enabling cross-device synchronization.",
)
async def get_saved_smart_reply_draft(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailReplyDraftResponse:
    """Retrieves the user's saved draft for the given message ID if one exists."""
    service = SmartReplyService(user_id=current_user.id, db=db)
    try:
        draft = await service.get_saved_reply_draft(message_id=message_id)
        if not draft:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No saved reply draft found for this message.",
            )
        return draft
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.put(
    "/messages/{message_id}/reply-draft",
    response_model=GmailReplyDraftResponse,
    summary="Save/Autosave Smart Reply Draft",
    description="Persists or updates an edited Smart Reply draft in cloud storage for cross-device retrieval.",
)
async def save_smart_reply_draft(
    message_id: str,
    payload: GmailReplyDraftSaveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailReplyDraftResponse:
    """Upserts the user's edited reply draft to PostgreSQL for seamless sync across devices."""
    service = SmartReplyService(user_id=current_user.id, db=db)
    try:
        return await service.save_reply_draft(
            message_id=message_id,
            reply_body=payload.reply_body,
            tone=payload.tone or "professional",
            custom_instructions=payload.custom_instructions,
            placeholders=payload.placeholders_detected,
            thread_id=payload.thread_id,
            subject=payload.subject,
            recipient=payload.recipient,
            gmail_draft_id=payload.gmail_draft_id,
        )
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.post(
    "/messages/{message_id}/save-to-gmail",
    response_model=GmailReplyDraftResponse,
    summary="Save Draft Directly to Gmail Mailbox",
    description="Creates or updates a real Gmail draft in the user's actual Gmail Drafts folder using Gmail API.",
)
async def save_draft_to_gmail_mailbox(
    message_id: str,
    payload: GmailReplyDraftSaveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GmailReplyDraftResponse:
    """
    Explicitly creates or updates a draft in the user's Google Gmail Drafts folder via Gmail API.
    Requires user confirmation and explicit click. Never sends emails automatically.
    """
    service = SmartReplyService(user_id=current_user.id, db=db)
    try:
        return await service.save_to_gmail_draft(
            message_id=message_id,
            reply_body=payload.reply_body,
            tone=payload.tone or "professional",
            custom_instructions=payload.custom_instructions,
            placeholders=payload.placeholders_detected,
            thread_id=payload.thread_id,
            subject=payload.subject,
            recipient=payload.recipient,
            gmail_draft_id=payload.gmail_draft_id,
        )
    except Exception as exc:
        raise _handle_service_exception(exc) from exc


@router.delete(
    "/messages/{message_id}/reply-draft",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard Smart Reply Draft",
    description="Deletes a saved Smart Reply draft from cloud storage and Gmail Drafts if present.",
)
async def delete_smart_reply_draft(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Discards and deletes the saved reply draft for the target email."""
    service = SmartReplyService(user_id=current_user.id, db=db)
    try:
        await service.delete_saved_reply_draft(message_id=message_id)
    except Exception as exc:
        raise _handle_service_exception(exc) from exc

