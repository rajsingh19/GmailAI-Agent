"""
Gmail Service.
Handles all direct interactions with the Google Gmail API.
Enforces multi-user isolation, bounded concurrency, token refresh via OAuthService,
and sanitized structured logging.

CRITICAL SECURITY RULES:
- Never log OAuth tokens, Authorization headers, or full raw payloads.
- Never log email body contents.
- Never accept user_id from untrusted sources; user_id is injected from the authenticated session.
- Scope all API calls strictly to the authenticated user's credentials.
"""
import asyncio
import base64
import email.message
from typing import Any, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.resilience import retry_with_backoff
from app.schemas.gmail import (
    GmailMessageDetail,
    GmailMessageListResponse,
    GmailMessageSummary,
    GmailProfileResponse,
)
from app.services.gmail_parser import GmailParser
from app.services.oauth_service import OAuthError, OAuthService, TokenRefreshError


# =============================================================================
# Domain Exceptions
# =============================================================================

class GmailServiceError(Exception):
    """Base exception for Gmail service errors."""
    pass


class GmailNotConnectedError(GmailServiceError):
    """Raised when the user has not connected a Google account."""
    pass


class GmailAuthenticationError(GmailServiceError):
    """Raised when Google account authentication is required, expired, or revoked."""
    pass


class GmailPermissionError(GmailServiceError):
    """Raised when Gmail access is forbidden or lacking scope."""
    pass


class GmailNotFoundError(GmailServiceError):
    """Raised when the requested message or resource is not found."""
    pass


class GmailRateLimitError(GmailServiceError):
    """Raised when Gmail API rate limits are encountered."""
    pass


class GmailCommunicationError(GmailServiceError):
    """Raised when a network or server error occurs communicating with Gmail."""
    pass


# =============================================================================
# Gmail Service Implementation
# =============================================================================

class GmailService:
    """Encapsulates all Google Gmail API operations for a specific authenticated user."""

    REQUIRED_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
    REQUIRED_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"

    def __init__(self, user_id: str, db: AsyncSession, max_concurrency: int = 10) -> None:
        self.user_id = user_id
        self.db = db
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _get_client(self, required_scope: Optional[str] = None) -> Any:
        """
        Validates granted scopes, retrieves a valid decrypted Google access token via OAuthService
        (auto-refreshing if expired) and builds a Gmail Resource client.
        """
        scope_to_check = required_scope or self.REQUIRED_SCOPE

        # 1. Verify Google Account and required scope
        has_scope = await OAuthService.has_required_scope(self.db, self.user_id, scope_to_check)
        if not has_scope:
            status_data = await OAuthService.get_connection_status(self.db, self.user_id)
            if not status_data.get("connected"):
                logger.info("No connected Google account for user_id=%s", self.user_id)
                raise GmailNotConnectedError("Google account is not connected.")
            logger.warning("User %s connected but missing scope: %s", self.user_id, scope_to_check)
            scope_name = scope_to_check.split("/")[-1]
            raise GmailPermissionError(
                f"Gmail permission '{scope_name}' is not authorized. Please reconnect your Google account with draft permissions."
            )

        try:
            access_token = await OAuthService.get_valid_access_token(self.db, self.user_id)
        except TokenRefreshError as exc:
            logger.warning("Token refresh failed for user_id=%s (revoked=%s)", self.user_id, exc.is_revoked)
            raise GmailAuthenticationError(
                "Google account authorization expired or was revoked. Please reconnect."
            ) from exc
        except OAuthError as exc:
            logger.info("No connected Google account for user_id=%s", self.user_id)
            raise GmailNotConnectedError("Google account is not connected.") from exc

        credentials = Credentials(token=access_token)
        # cache_discovery=False prevents local filesystem cache writes and avoids warnings
        return await asyncio.to_thread(
            build, "gmail", "v1", credentials=credentials, cache_discovery=False
        )

    async def get_profile(self) -> GmailProfileResponse:
        """
        Retrieves the authenticated user's Gmail profile summary.
        Safe, non-sensitive metrics only.
        """
        client = await self._get_client()

        def _fetch():
            return client.users().getProfile(userId="me").execute()

        try:
            profile_data = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch),
                operation_name="get_profile",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation="get_profile")
        except Exception as exc:
            logger.error("Unexpected error fetching Gmail profile for user_id=%s: %s", self.user_id, type(exc).__name__)
            raise GmailCommunicationError("Unable to communicate with Gmail.") from exc

        return GmailProfileResponse(
            email=profile_data.get("emailAddress", ""),
            messages_total=int(profile_data.get("messagesTotal", 0)),
            threads_total=int(profile_data.get("threadsTotal", 0)),
            history_id=str(profile_data.get("historyId", "")) if profile_data.get("historyId") else None,
        )

    async def list_messages(
        self,
        max_results: int = 20,
        page_token: Optional[str] = None,
        query: Optional[str] = None,
    ) -> GmailMessageListResponse:
        """
        Lists message summaries matching the query or latest in inbox.
        Uses bounded concurrency (max 10 parallel requests) to fetch metadata.
        """
        # Enforce bounds
        bounded_max = max(1, min(max_results, 100))
        client = await self._get_client()

        params: Dict[str, Any] = {
            "userId": "me",
            "maxResults": bounded_max,
        }
        if page_token:
            params["pageToken"] = page_token
        if query:
            params["q"] = query

        def _fetch_list():
            return client.users().messages().list(**params).execute()

        try:
            list_res = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch_list),
                operation_name="list_messages",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation="list_messages")
        except Exception as exc:
            logger.error("Unexpected error listing messages for user_id=%s: %s", self.user_id, type(exc).__name__)
            raise GmailCommunicationError("Unable to communicate with Gmail.") from exc

        raw_messages = list_res.get("messages", []) or []
        next_page_token = list_res.get("nextPageToken")
        result_size_estimate = int(list_res.get("resultSizeEstimate", 0))

        if not raw_messages:
            return GmailMessageListResponse(
                messages=[],
                next_page_token=next_page_token,
                result_size_estimate=result_size_estimate,
            )

        # Batch fetch message summaries via Google API Batch HttpRequest (fast, single HTTP call)
        summaries: List[GmailMessageSummary] = []
        batch_results: Dict[str, Any] = {}

        def _execute_batch():
            def _batch_cb(req_id, resp, exc):
                if exc is None and resp:
                    batch_results[req_id] = resp

            batch = client.new_batch_http_request(callback=_batch_cb)
            for m in raw_messages:
                mid = m.get("id")
                if mid:
                    batch.add(
                        client.users().messages().get(
                            userId="me",
                            id=mid,
                            format="metadata",
                            metadataHeaders=["Subject", "From", "To", "Date"],
                        ),
                        request_id=mid,
                    )
            batch.execute()

        try:
            await asyncio.to_thread(_execute_batch)
            for m in raw_messages:
                mid = m.get("id")
                if mid and mid in batch_results:
                    summaries.append(GmailParser.parse_message_summary(batch_results[mid]))
        except Exception as batch_exc:
            logger.warning("Batch metadata fetch failed, using bounded fallback: %s", type(batch_exc).__name__)

        # If batch returned no summaries (e.g. in mocked test environments), use bounded fallback
        if not summaries and raw_messages:
            async def _fetch_single_summary(msg_ref: Dict[str, str]) -> Optional[GmailMessageSummary]:
                msg_id = msg_ref.get("id")
                if not msg_id:
                    return None
                async with self._semaphore:
                    def _get_meta():
                        return client.users().messages().get(
                            userId="me",
                            id=msg_id,
                            format="metadata",
                            metadataHeaders=["Subject", "From", "To", "Date"],
                        ).execute()

                    try:
                        meta_res = await asyncio.to_thread(_get_meta)
                        return GmailParser.parse_message_summary(meta_res)
                    except Exception as exc:
                        logger.warning("Failed to fetch metadata for msg_id=%s: %s", msg_id, type(exc).__name__)
                        return None

            tasks = [_fetch_single_summary(m) for m in raw_messages]
            results = await asyncio.gather(*tasks, return_exceptions=False)
            summaries = [s for s in results if s is not None]

        logger.info(
            "Retrieved %d message summaries for user_id=%s (estimate=%d)",
            len(summaries),
            self.user_id,
            result_size_estimate,
        )

        return GmailMessageListResponse(
            messages=summaries,
            next_page_token=next_page_token,
            result_size_estimate=result_size_estimate,
        )

    async def get_message(self, message_id: str) -> GmailMessageDetail:
        """
        Retrieves full normalized email details for a specific message ID.
        Extracts plain text and sanitized HTML text; attachment metadata only.
        """
        if not message_id or not message_id.strip():
            raise GmailNotFoundError("Invalid or empty message ID.")

        clean_id = message_id.strip()
        client = await self._get_client()

        def _fetch_full():
            return client.users().messages().get(
                userId="me",
                id=clean_id,
                format="full",
            ).execute()

        try:
            raw_msg = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch_full),
                operation_name=f"get_message({clean_id})",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation=f"get_message({clean_id})")
        except Exception as exc:
            logger.error("Unexpected error fetching message %s for user_id=%s: %s", clean_id, self.user_id, type(exc).__name__)
            raise GmailCommunicationError("Unable to communicate with Gmail.") from exc

        detail = GmailParser.parse_message_detail(raw_msg)
        logger.info("Successfully fetched message detail for msg_id=%s, user_id=%s", clean_id, self.user_id)
        return detail

    async def get_thread(self, thread_id: str) -> List[GmailMessageDetail]:
        """
        Retrieves all messages in a specific email thread, ordered chronologically.
        Parses full message details for thread-level contextual awareness.
        """
        if not thread_id or not thread_id.strip():
            return []

        clean_id = thread_id.strip()
        client = await self._get_client()

        def _fetch_thread():
            return client.users().threads().get(
                userId="me",
                id=clean_id,
                format="full",
            ).execute()

        try:
            raw_thread = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch_thread),
                operation_name=f"get_thread({clean_id})",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation=f"get_thread({clean_id})")
        except Exception as exc:
            logger.error("Unexpected error fetching thread %s for user_id=%s: %s", clean_id, self.user_id, type(exc).__name__)
            raise GmailCommunicationError("Unable to communicate with Gmail.") from exc

        raw_messages = raw_thread.get("messages", []) if isinstance(raw_thread, dict) else []
        thread_details: List[GmailMessageDetail] = []
        for m in raw_messages:
            try:
                thread_details.append(GmailParser.parse_message_detail(m))
            except Exception as parse_exc:
                logger.warning("Failed parsing message in thread %s: %s", clean_id, type(parse_exc).__name__)

        logger.info("Successfully fetched %d messages for thread_id=%s, user_id=%s", len(thread_details), clean_id, self.user_id)
        return thread_details

    async def create_or_update_draft(
        self,
        reply_body: str,
        subject: Optional[str] = None,
        recipient: Optional[str] = None,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        existing_draft_id: Optional[str] = None,
        attachment_bytes: Optional[bytes] = None,
        attachment_filename: Optional[str] = None,
        attachment_mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates or updates a real Gmail draft in the user's actual Gmail Drafts folder using Gmail API.
        Guarantees:
        - Thread association via threadId
        - Correct In-Reply-To and References headers
        - Clean MIME RFC-2822 base64url encoding
        - Safe in-memory attachment handling (PDF, DOCX, TXT)
        - Explicit draft update if existing_draft_id is supplied, fallback to create if 404
        - NEVER sends emails automatically
        """
        client = await self._get_client(required_scope=self.REQUIRED_COMPOSE_SCOPE)

        mime_msg = email.message.EmailMessage()
        mime_msg.set_content(reply_body)
        if recipient:
            mime_msg["To"] = recipient
        if subject:
            mime_msg["Subject"] = subject
        if in_reply_to:
            mime_msg["In-Reply-To"] = in_reply_to
            mime_msg["References"] = in_reply_to

        if attachment_bytes and attachment_filename:
            maintype = "application"
            subtype = "octet-stream"
            if attachment_mime_type and "/" in attachment_mime_type:
                parts = attachment_mime_type.split("/", 1)
                maintype, subtype = parts[0], parts[1]
            mime_msg.add_attachment(
                attachment_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=attachment_filename,
            )

        raw_b64 = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("ascii")

        draft_message_payload: Dict[str, Any] = {"raw": raw_b64}
        if thread_id:
            draft_message_payload["threadId"] = thread_id

        draft_payload = {"message": draft_message_payload}

        def _execute_save():
            if existing_draft_id:
                try:
                    return client.users().drafts().update(
                        userId="me", id=existing_draft_id, body=draft_payload
                    ).execute()
                except HttpError as update_err:
                    status = update_err.resp.status if hasattr(update_err, "resp") and hasattr(update_err.resp, "status") else None
                    if status == 404:
                        logger.info("Existing draft %s not found in Gmail, creating fresh draft", existing_draft_id)
                        return client.users().drafts().create(userId="me", body=draft_payload).execute()
                    raise
            return client.users().drafts().create(userId="me", body=draft_payload).execute()

        try:
            res = await retry_with_backoff(
                lambda: asyncio.to_thread(_execute_save),
                operation_name="create_or_update_draft",
            )
        except HttpError as exc:
            self._handle_http_error(exc, operation="create_or_update_draft")
        except Exception as exc:
            logger.error("Error creating/updating draft for user_id=%s: %s", self.user_id, type(exc).__name__)
            raise GmailCommunicationError("Failed to save draft to Gmail.") from exc

        draft_id = res.get("id")
        created_msg = res.get("message", {}) or {}
        created_thread_id = created_msg.get("threadId") or thread_id

        logger.info(
            "Successfully saved draft to Gmail for user_id=%s, draft_id=%s, thread_id=%s",
            self.user_id,
            draft_id,
            created_thread_id,
        )

        return {
            "draft_id": draft_id,
            "message_id": created_msg.get("id"),
            "thread_id": created_thread_id,
            "gmail_web_url": "https://mail.google.com/mail/u/0/#drafts",
        }

    async def get_draft(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific draft directly from the Gmail API."""
        if not draft_id or not draft_id.strip():
            return None

        clean_draft_id = draft_id.strip()
        client = await self._get_client(required_scope=self.REQUIRED_COMPOSE_SCOPE)

        def _fetch():
            return client.users().drafts().get(userId="me", id=clean_draft_id, format="full").execute()

        try:
            raw_draft = await retry_with_backoff(
                lambda: asyncio.to_thread(_fetch),
                operation_name=f"get_draft({clean_draft_id})",
            )
            return raw_draft
        except HttpError as exc:
            status = exc.resp.status if hasattr(exc, "resp") and hasattr(exc.resp, "status") else None
            if status == 404:
                return None
            self._handle_http_error(exc, operation=f"get_draft({clean_draft_id})")
        except Exception as exc:
            logger.warning("Error fetching Gmail draft %s: %s", clean_draft_id, type(exc).__name__)
            return None

    async def delete_draft(self, draft_id: str) -> bool:
        """Deletes a draft from the user's Gmail Mailbox."""
        if not draft_id or not draft_id.strip():
            return False

        clean_draft_id = draft_id.strip()
        client = await self._get_client(required_scope=self.REQUIRED_COMPOSE_SCOPE)

        def _execute_delete():
            return client.users().drafts().delete(userId="me", id=clean_draft_id).execute()

        try:
            await retry_with_backoff(
                lambda: asyncio.to_thread(_execute_delete),
                operation_name=f"delete_draft({clean_draft_id})",
            )
            logger.info("Deleted Gmail draft %s for user_id=%s", clean_draft_id, self.user_id)
            return True
        except HttpError as exc:
            status = exc.resp.status if hasattr(exc, "resp") and hasattr(exc.resp, "status") else None
            if status == 404:
                return True
            self._handle_http_error(exc, operation=f"delete_draft({clean_draft_id})")
        except Exception as exc:
            logger.warning("Error deleting Gmail draft %s: %s", clean_draft_id, type(exc).__name__)
            return False


    def _handle_http_error(self, exc: HttpError, operation: str) -> None:
        """Translates Google HttpError into clean domain exceptions without leaking secrets."""
        status_code = exc.resp.status if hasattr(exc, "resp") and hasattr(exc.resp, "status") else 500

        logger.warning(
            "Gmail API HttpError during %s for user_id=%s (HTTP %d)",
            operation,
            self.user_id,
            status_code,
        )

        if status_code == 401:
            raise GmailAuthenticationError("Google account authentication is required.")
        elif status_code == 403:
            raise GmailPermissionError("Gmail access is not available for this account.")
        elif status_code == 404:
            raise GmailNotFoundError("Email message not found.")
        elif status_code == 429:
            raise GmailRateLimitError("Gmail API rate limit reached. Please try again later.")
        elif status_code >= 500:
            raise GmailCommunicationError("Unable to communicate with Gmail.")
        else:
            raise GmailCommunicationError(f"Gmail API error (HTTP {status_code}).")
