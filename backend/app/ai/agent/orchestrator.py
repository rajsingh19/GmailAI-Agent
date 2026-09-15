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
)
from app.ai.providers.gemini_provider import GeminiProvider
from app.ai.agent.tool_registry import ToolRegistry
from app.ai.agent.tool_executor import ToolExecutor, ToolExecutionResult
from app.ai.agent.prompts import get_agent_system_instruction
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

    async def process_message(
        self,
        user: User,
        db: AsyncSession,
        message: str,
        history: Optional[List[AgentChatMessage]] = None,
        confirmation_token: Optional[str] = None,
    ) -> AgentChatResponse:
        """
        Processes a single user message turn with safe multi-step tool execution.
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

        # 3. System prompt & tools
        now_iso = datetime.now(timezone.utc).isoformat()
        sys_instruction = get_agent_system_instruction(user_email=user.email, current_time_iso=now_iso)
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

                    tool_activities.append(
                        ToolActivityInfo(
                            name=friendly_name,
                            status=exec_res.status,
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
        except LLMRateLimitError as exc:
            logger.warning("[%s] LLM Rate Limit Error: %s", execution_id, exc)
            final_answer = "The AI service is temporarily busy (rate limit reached). Please try again in a moment."
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

        return AgentChatResponse(
            message=final_answer,
            execution_id=execution_id,
            tool_activities=tool_activities,
            confirmation_required=confirmation_required,
            metadata={
                "model": getattr(self.provider, "model_name", "unknown"),
                "duration_ms": duration_ms,
                "tool_calls_count": len(tool_activities),
            },
        )
