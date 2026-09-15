import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolDefinition, ToolRegistry, RiskLevel
from app.services.gmail_service import (
    GmailService,
    GmailNotConnectedError,
    GmailAuthenticationError,
    GmailPermissionError,
    GmailNotFoundError,
    GmailServiceError,
)

logger = logging.getLogger(__name__)


async def execute_get_gmail_profile(
    user_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Tool to fetch the connected Gmail profile summary (email address, total messages)."""
    service = GmailService(user_id=user_id, db=db)
    try:
        profile = await service.get_profile()
        return {
            "source": "gmail",
            "trusted": False,
            "status": "success",
            "profile": {
                "email": profile.email,
                "messages_total": profile.messages_total,
                "threads_total": profile.threads_total,
            },
        }
    except GmailNotConnectedError:
        return {"source": "gmail", "trusted": False, "status": "error", "message": "Google account is not connected. Please connect Google account first."}
    except GmailAuthenticationError:
        return {"source": "gmail", "trusted": False, "status": "error", "message": "Google authentication expired or revoked. Please reconnect."}
    except Exception as exc:
        return {"source": "gmail", "trusted": False, "status": "error", "message": f"Failed to get Gmail profile: {exc}"}


async def execute_search_gmail(
    user_id: str,
    db: AsyncSession,
    query: str,
    max_results: Optional[int] = 5,
) -> Dict[str, Any]:
    """Tool to search user Gmail messages using standard Gmail query syntax (e.g. from:x, is:unread, subject:y)."""
    lim = min(max(max_results or 5, 1), 10)
    service = GmailService(user_id=user_id, db=db)
    try:
        resp = await service.list_messages(max_results=lim, query=query)
        messages = [
            {
                "id": m.id,
                "subject": m.subject,
                "sender": m.sender,
                "timestamp": m.timestamp,
                "snippet": m.snippet,
                "is_unread": m.is_unread,
                "has_attachments": m.has_attachments,
            }
            for m in resp.messages
        ]
        return {
            "source": "gmail",
            "trusted": False,
            "status": "success",
            "query": query,
            "count": len(messages),
            "messages": messages,
        }
    except GmailNotConnectedError:
        return {"source": "gmail", "trusted": False, "status": "error", "message": "Google account is not connected."}
    except GmailAuthenticationError:
        return {"source": "gmail", "trusted": False, "status": "error", "message": "Google authentication expired or revoked."}
    except Exception as exc:
        return {"source": "gmail", "trusted": False, "status": "error", "message": f"Gmail search error: {exc}"}


async def execute_list_gmail_messages(
    user_id: str,
    db: AsyncSession,
    max_results: Optional[int] = 5,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """Tool to list recent messages from the inbox."""
    return await execute_search_gmail(user_id=user_id, db=db, query=query or "", max_results=max_results)


async def execute_get_gmail_message(
    user_id: str,
    db: AsyncSession,
    message_id: str,
) -> Dict[str, Any]:
    """Tool to retrieve safe text content of a specific email message."""
    service = GmailService(user_id=user_id, db=db)
    try:
        msg = await service.get_message(message_id=message_id)

        # Output minimization: extract clean plain text or sanitized HTML text, bounded to 2000 chars
        body_text = msg.body_plain or msg.body_html_text or msg.snippet or ""
        if len(body_text) > 2000:
            body_text = body_text[:2000] + "... [TRUNCATED]"

        attachments = [
            {"filename": a.filename, "size": a.size, "mime_type": a.mime_type}
            for a in msg.attachments
        ]

        return {
            "source": "gmail",
            "trusted": False,
            "status": "success",
            "message": {
                "id": msg.id,
                "subject": msg.subject,
                "sender": msg.sender,
                "recipients": msg.recipients,
                "timestamp": msg.timestamp,
                "body": body_text,
                "attachments": attachments,
                "is_unread": msg.is_unread,
            },
        }
    except GmailNotFoundError:
        return {"source": "gmail", "trusted": False, "status": "error", "message": f"Email message '{message_id}' not found."}
    except (GmailNotConnectedError, GmailAuthenticationError) as exc:
        return {"source": "gmail", "trusted": False, "status": "error", "message": str(exc)}
    except Exception as exc:
        return {"source": "gmail", "trusted": False, "status": "error", "message": f"Failed to get message: {exc}"}


def register_gmail_tools() -> None:
    """Registers all read-only Gmail tools into ToolRegistry."""
    ToolRegistry.register(
        ToolDefinition(
            name="get_gmail_profile",
            description="Retrieve basic connected Gmail profile metadata (email address, total message count).",
            friendly_name="Fetching Gmail profile",
            risk_level=RiskLevel.READ,
            func=execute_get_gmail_profile,
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="search_gmail",
            description="Search Gmail messages using query operators (e.g., 'from:boss', 'is:unread', 'subject:meeting').",
            friendly_name="Searching Gmail",
            risk_level=RiskLevel.READ,
            func=execute_search_gmail,
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string (e.g. 'is:unread', 'from:alice@example.com')"},
                    "max_results": {"type": "integer", "description": "Max emails to inspect (default 5, max 10)"},
                },
                "required": ["query"],
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="list_gmail_messages",
            description="List recent Gmail messages from the inbox.",
            friendly_name="Listing emails",
            risk_level=RiskLevel.READ,
            func=execute_list_gmail_messages,
            parameters_schema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Max emails to return (default 5, max 10)"},
                    "query": {"type": "string", "description": "Optional search filter"},
                },
            },
        )
    )

    ToolRegistry.register(
        ToolDefinition(
            name="get_gmail_message",
            description="Retrieve full sanitized text content, subject, sender, and attachment metadata of an email by message ID.",
            friendly_name="Reading email",
            risk_level=RiskLevel.READ,
            func=execute_get_gmail_message,
            parameters_schema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "The unique Gmail message ID"},
                },
                "required": ["message_id"],
            },
        )
    )
