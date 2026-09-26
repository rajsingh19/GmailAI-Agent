import time
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User
from app.ai.providers.base import (
    LLMProvider,
    LLMMessage,
    LLMResponse,
    LLMProviderError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMServiceUnavailableError,
)
from app.ai.providers.gemini_provider import GeminiProvider
from app.ai.agent.tool_registry import ToolRegistry
from app.ai.agent.tool_executor import ToolExecutor, ToolExecutionResult
from app.ai.agent.prompts import get_agent_system_instruction, format_memory_context
from app.ai.schemas.agent import (
    AgentChatMessage,
    AgentChatResponse,
    ToolActivityInfo,
    ConfirmationChallenge,
)

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """
    Coordinates multi-turn conversational dialogue and safe tool calling for the AI Agent.
    Enforces maximum tool execution bounds, client history sanitization, execution ID telemetry,
    and untrusted external data boundaries.
    """

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.effective_model_name,
        )

    def _sanitize_history(self, history: Optional[List[AgentChatMessage]]) -> List[LLMMessage]:
        """
        Sanitizes client-provided history:
        - Only accepts 'user' and 'assistant' roles
        - Rejects any client-supplied 'system' or 'tool' messages
        - Binds total message count and total character count
        """
        if not history:
            return []

        sanitized: List[LLMMessage] = []
        total_chars = 0

        # Take at most the last MAX_HISTORY_MESSAGES
        bounded_history = history[-settings.MAX_HISTORY_MESSAGES:]

        for msg in bounded_history:
            if msg.role not in ("user", "assistant"):
                continue  # Skip invalid roles

            content = msg.content.strip()
            if not content:
                continue

            if total_chars + len(content) > settings.MAX_HISTORY_CHARS:
                break

            total_chars += len(content)
            role_mapped = "user" if msg.role == "user" else "model"
            sanitized.append(LLMMessage(role=role_mapped, content=content))

        return sanitized

    def _synthesize_tool_fallback_response(
        self,
        tool_activities: List[ToolActivityInfo],
        llm_messages: List[LLMMessage],
        clean_message: str,
        default_rate_limit_msg: str,
    ) -> str:
        """
        When the final LLM synthesis step is rate-limited (HTTP 429) or temporarily unavailable (HTTP 503),
        synthesizes a structured, high-reliability response directly from successfully executed tool outputs
        instead of losing the user's data.
        """
        tool_results = [msg for msg in llm_messages if msg.role == "tool" and msg.tool_response]
        if not tool_results:
            return default_rate_limit_msg

        # Check if Gmail search was executed
        gmail_res = next((msg.tool_response for msg in tool_results if msg.tool_name in ("search_gmail", "list_gmail_messages")), None)
        if gmail_res:
            if gmail_res.get("status") == "error":
                return f"{gmail_res.get('message', 'Unable to retrieve Gmail messages.')}"

            messages = gmail_res.get("messages", [])
            if not messages:
                return f"I searched your Gmail, but found no matching messages for '{gmail_res.get('query', '')}'."

            # Check for upcoming / pending interview messages
            upcoming = [m for m in messages if m.get("is_pending_or_upcoming") is True]
            expired = [m for m in messages if m.get("interview_temporal_status") in ("EXPIRED_PAST", "HISTORICAL")]

            lines = ["Here are the interview details found in your Gmail:"]
            if upcoming:
                lines.append("\n**Upcoming & Pending Interviews:**")
                for u in upcoming:
                    subj = u.get("subject", "Interview")
                    sender = u.get("sender", "Unknown")
                    sched = u.get("interview_scheduled_time") or u.get("timestamp", "Upcoming")
                    status_lbl = u.get("interview_temporal_status", "UPCOMING")
                    lines.append(f"• **[{status_lbl}] {subj}**\n  - Scheduled / Deadline: {sched}\n  - From: {sender}")
            elif expired and any(w in clean_message.lower() for w in ("upcoming", "pending", "scheduled")):
                lines.append("\n*No upcoming or pending interviews found. All identified interview invitations in your inbox are past or completed.*")
            else:
                lines.append("\n**Recent Email Summaries:**")
                for m in messages:
                    lines.append(f"• **{m.get('subject', '(No Subject)')}** (From: {m.get('sender', 'Unknown')}) - {m.get('snippet', '')[:100]}...")

            return "\n".join(lines)

        # Check if Calendar list was executed
        cal_res = next((msg.tool_response for msg in tool_results if msg.tool_name in ("list_calendar_events", "list_user_calendars")), None)
        if cal_res:
            if cal_res.get("status") == "error":
                return f"{cal_res.get('message', 'Unable to retrieve Calendar events.')}"
            events = cal_res.get("events", [])
            if not events:
                return "You have no upcoming calendar events scheduled for this period."
            lines = ["Here are your upcoming calendar events:"]
            for ev in events:
                lines.append(f"• **{ev.get('summary', 'Untitled Event')}**\n  - Start: {ev.get('start')}\n  - Location: {ev.get('location') or 'Not specified'}")
            return "\n".join(lines)

        # Check if Task list was executed
        task_res = next((msg.tool_response for msg in tool_results if msg.tool_name == "list_tasks"), None)
        if task_res:
            tasks = task_res.get("items", [])
            if not tasks:
                return "You have no pending tasks."
            lines = ["Here are your current tasks:"]
            for t in tasks:
                lines.append(f"• [{t.get('status')}] **{t.get('title')}** (Priority: {t.get('priority')})")
            return "\n".join(lines)

        return default_rate_limit_msg

    async def process_message(
        self,
        user: User,
        db: AsyncSession,
        message: str,
        history: Optional[List[AgentChatMessage]] = None,
        confirmation_token: Optional[str] = None,
        session_id: Optional[str] = None,
        disable_personalization: bool = False,
    ) -> AgentChatResponse:
        """
        Processes a single user message turn with safe multi-step tool execution.
        Integrates M12 Personalization Intelligence & Policy layer.
        """
        execution_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        logger.info(
            "[%s] Starting agent execution turn for user_id=%s (email=%s)",
            execution_id,
            user.id[:8],
            user.email,
        )

        # 1. Truncate oversized user message
        clean_message = message.strip()[:settings.MAX_AGENT_MESSAGE_LENGTH]
        if not clean_message:
            return AgentChatResponse(
                message="Please provide a message or instruction.",
                execution_id=execution_id,
                tool_activities=[],
                metadata={"model": getattr(self.provider, "model_name", "unknown"), "duration_ms": 0},
            )

        # 2. Build conversation context
        llm_messages: List[LLMMessage] = self._sanitize_history(history)
        llm_messages.append(LLMMessage(role="user", content=clean_message))

        # 3. System prompt & tools (with bounded M12 personalization context)
        from app.services.personalization_service import PersonalizationService
        now_iso = datetime.now(timezone.utc).isoformat()
        personalization_res = await PersonalizationService.build_personalization_context(
            db=db,
            user_id=user.id,
            query=clean_message,
            session_id=session_id,
            disable_personalization=disable_personalization,
        )
        sys_instruction = get_agent_system_instruction(
            user_email=user.email,
            current_time_iso=now_iso,
            memory_context=personalization_res.context_text,
        )
        tool_declarations = ToolRegistry.get_tool_declarations()

        tool_activities: List[ToolActivityInfo] = []
        confirmation_required: Optional[ConfirmationChallenge] = None
        turn_count = 0
        final_answer = "I was unable to complete the request."

        try:
            # 4. Bounded tool-calling execution loop
            while turn_count < settings.MAX_TOOL_CALLS_PER_TURN:
                turn_count += 1

                logger.info(
                    "[%s] Calling LLM turn %d/%d with %d messages and %d tools",
                    execution_id,
                    turn_count,
                    settings.MAX_TOOL_CALLS_PER_TURN,
                    len(llm_messages),
                    len(tool_declarations),
                )

                llm_resp: LLMResponse = await self.provider.generate_response(
                    messages=llm_messages,
                    tools=tool_declarations,
                    system_instruction=sys_instruction,
                    timeout=float(settings.AGENT_TIMEOUT_SECONDS),
                )

                # If LLM did not request any tools, we have our final synthesized text answer
                if not llm_resp.tool_calls:
                    final_answer = llm_resp.content or "Done."
                    break

                # If LLM produced both partial content and tool calls, add model step
                llm_messages.append(
                    LLMMessage(
                        role="model",
                        content=llm_resp.content,
                        tool_calls=llm_resp.tool_calls,
                    )
                )

                # Execute requested tools
                for tc in llm_resp.tool_calls:
                    exec_res: ToolExecutionResult = await ToolExecutor.execute_tool(
                        user_id=user.id,
                        db=db,
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        confirmation_token=confirmation_token,
                        execution_id=execution_id,
                    )

                    tool_def = ToolRegistry.get(tc.name)
                    friendly_name = tool_def.friendly_name if tool_def else tc.name

                    status_mapped = "completed" if exec_res.status in ("completed", "success") else (
                        "confirmation_required" if exec_res.status == "confirmation_required" else "failed"
                    )
                    tool_activities.append(
                        ToolActivityInfo(
                            name=friendly_name,
                            status=status_mapped,
                            summary=exec_res.friendly_summary,
                        )
                    )

                    if exec_res.confirmation_challenge:
                        confirmation_required = exec_res.confirmation_challenge
                        final_answer = exec_res.confirmation_challenge.message
                        break

                    # Feed structured tool result back into context
                    llm_messages.append(
                        LLMMessage(
                            role="tool",
                            tool_name=tc.name,
                            tool_response=exec_res.result_payload,
                        )
                    )

                if confirmation_required:
                    break

            else:
                logger.warning("[%s] Max tool calls (%d) reached in turn", execution_id, settings.MAX_TOOL_CALLS_PER_TURN)
                final_answer = "I have reached the maximum number of actions for this request. Please see the activities above or refine your query."

        except LLMAuthenticationError as exc:
            logger.warning("[%s] LLM Authentication Error: %s", execution_id, exc)
            final_answer = "The AI service credentials appear to be invalid or unconfigured. Please check backend settings."
        except (LLMRateLimitError, LLMServiceUnavailableError) as exc:
            logger.warning("[%s] LLM %s on turn %d: %s", execution_id, type(exc).__name__, turn_count, exc)
            retry_secs = int(round(exc.retry_after)) if exc.retry_after and exc.retry_after > 0 else 30
            default_err_msg = (
                f"The AI service is temporarily busy (rate limit reached). Please try again in ~{retry_secs} seconds."
                if isinstance(exc, LLMRateLimitError)
                else f"The AI service is temporarily experiencing high demand. Please try again in ~{retry_secs} seconds."
            )

            # If tools were already executed during this turn, synthesize the answer from the retrieved data!
            if tool_activities:
                final_answer = self._synthesize_tool_fallback_response(
                    tool_activities=tool_activities,
                    llm_messages=llm_messages,
                    clean_message=clean_message,
                    default_rate_limit_msg=default_err_msg,
                )
            else:
                # Direct intent fallback for common read-only actions when planning turn is rate-limited
                lower_q = clean_message.lower()
                if any(w in lower_q for w in ("interview", "interviews")):
                    from app.ai.tools.gmail_tools import execute_search_gmail
                    try:
                        g_res = await execute_search_gmail(user_id=user.id, db=db, query="interview")
                        llm_messages.append(LLMMessage(role="tool", tool_name="search_gmail", tool_response=g_res))
                        is_ok = g_res.get("status") == "success"
                        tool_activities.append(
                            ToolActivityInfo(
                                name="Searching Gmail",
                                status="completed" if is_ok else "failed",
                                summary=f"Found {g_res.get('count', 0)} messages" if is_ok else (g_res.get("message") or "Failed to search Gmail"),
                            )
                        )
                        final_answer = self._synthesize_tool_fallback_response(
                            tool_activities=tool_activities,
                            llm_messages=llm_messages,
                            clean_message=clean_message,
                            default_rate_limit_msg=default_err_msg,
                        )
                    except Exception as fallback_exc:
                        logger.warning("[%s] Direct interview fallback failed: %s", execution_id, fallback_exc)
                        final_answer = default_err_msg
                else:
                    final_answer = default_err_msg
        except LLMTimeoutError as exc:
            logger.warning("[%s] LLM Timeout Error: %s", execution_id, exc)
            final_answer = "The AI service timed out while processing your request. Please try again."
        except LLMProviderError as exc:
            logger.warning("[%s] LLM Provider Error: %s", execution_id, exc)
            final_answer = "An error occurred while communicating with the AI model."
        except Exception as exc:
            logger.exception("[%s] Unexpected agent error: %s", execution_id, exc)
            final_answer = "An unexpected error occurred while processing your request."

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        logger.info(
            "[%s] Completed agent execution in %.2f ms (tools_used=%d, confirmation_required=%s)",
            execution_id,
            duration_ms,
            len(tool_activities),
            bool(confirmation_required),
        )

        meta_dict = {
            "model": getattr(self.provider, "model_name", "unknown"),
            "duration_ms": duration_ms,
            "tool_calls_count": len(tool_activities),
        }
        p_meta = personalization_res.metadata.model_dump() if "personalization_res" in locals() and personalization_res.metadata else None
        if p_meta:
            meta_dict["personalization_metadata"] = p_meta

        return AgentChatResponse(
            message=final_answer,
            execution_id=execution_id,
            tool_activities=tool_activities,
            confirmation_required=confirmation_required,
            metadata=meta_dict,
            personalization_metadata=p_meta,
        )
