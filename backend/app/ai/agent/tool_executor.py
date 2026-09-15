import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ai.agent.tool_registry import ToolRegistry, RiskLevel, ToolDefinition
from app.ai.agent.confirmation import ConfirmationService
from app.ai.schemas.agent import ConfirmationChallenge

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionResult:
    """Standardized output of a tool execution attempt."""
    tool_name: str
    status: str  # "completed", "failed", "confirmation_required"
    result_payload: Dict[str, Any]
    friendly_summary: str
    is_error: bool = False
    confirmation_challenge: Optional[ConfirmationChallenge] = None


class ToolExecutor:
    """
    Executes tools requested by the AI Agent with strict security boundaries:
    - Injects verified authenticated user_id (ignores model-supplied user_id)
    - Enforces static tool whitelist
    - Enforces server-issued confirmation tokens for HIGH_RISK_WRITE tools
    - Enforces per-tool execution timeouts
    - Segregates and sanitizes untrusted tool outputs
    """

    @classmethod
    async def execute_tool(
        cls,
        user_id: str,
        db: AsyncSession,
        tool_name: str,
        arguments: Dict[str, Any],
        confirmation_token: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> ToolExecutionResult:
        """Executes a single tool call with authorization and timeout guardrails."""
        tool: Optional[ToolDefinition] = ToolRegistry.get(tool_name)

        if not tool or not tool.func:
            logger.warning("[%s] Model requested unknown or unregistered tool: %s", execution_id or "AGENT", tool_name)
            return ToolExecutionResult(
                tool_name=tool_name,
                status="failed",
                result_payload={"status": "error", "message": f"Tool '{tool_name}' is not authorized or does not exist."},
                friendly_summary=f"Unauthorized tool '{tool_name}' rejected",
                is_error=True,
            )

        # 1. Strip any client/model attempt to override user_id or db
        safe_args = {k: v for k, v in arguments.items() if k not in ("user_id", "db", "authenticated_user_id")}

        # 2. Enforce HIGH_RISK_WRITE confirmation challenge
        if tool.risk_level == RiskLevel.HIGH_RISK_WRITE:
            target_param = tool.target_id_param or "id"
            target_id = str(safe_args.get(target_param, ""))

            if not target_id:
                return ToolExecutionResult(
                    tool_name=tool_name,
                    status="failed",
                    result_payload={"status": "error", "message": f"Missing target identifier '{target_param}' for high-risk tool."},
                    friendly_summary="Missing resource identifier for action",
                    is_error=True,
                )

            # Validate server-issued confirmation token
            is_confirmed = False
            if confirmation_token:
                is_confirmed = ConfirmationService.verify_and_consume(
                    token=confirmation_token,
                    user_id=user_id,
                    tool_name=tool_name,
                    target_id=target_id,
                    action="delete",
                )

            if not is_confirmed:
                # Issue new challenge token
                challenge_token = ConfirmationService.issue_challenge(
                    user_id=user_id,
                    tool_name=tool_name,
                    target_id=target_id,
                    action="delete",
                )
                challenge = ConfirmationChallenge(
                    tool=tool_name,
                    target_id=target_id,
                    action="delete",
                    confirmation_token=challenge_token,
                    message=f"Action '{tool.friendly_name}' on item '{target_id}' requires explicit user confirmation.",
                )
                logger.info("[%s] High-risk tool '%s' on target '%s' paused for confirmation challenge", execution_id or "AGENT", tool_name, target_id)
                return ToolExecutionResult(
                    tool_name=tool_name,
                    status="confirmation_required",
                    result_payload={
                        "status": "confirmation_required",
                        "tool": tool_name,
                        "target_id": target_id,
                        "message": f"Confirmation required to {tool.friendly_name.lower()} '{target_id}'.",
                    },
                    friendly_summary=f"Confirmation required to {tool.friendly_name.lower()}",
                    confirmation_challenge=challenge,
                )

        # 3. Execute with timeout
        timeout = float(settings.TOOL_TIMEOUT_SECONDS)
        try:
            logger.info("[%s] Executing tool '%s' for user_id=%s (timeout=%.1fs)", execution_id or "AGENT", tool_name, user_id[:8], timeout)
            res_dict = await asyncio.wait_for(
                tool.func(user_id=user_id, db=db, **safe_args),
                timeout=timeout,
            )

            # 4. Truncate oversized output
            res_str = json.dumps(res_dict)
            if len(res_str) > settings.MAX_TOOL_RESULT_CHARS:
                res_dict["_warning"] = "Result payload was truncated to fit context limits."

            # Construct user-friendly summary
            friendly_summary = f"Completed {tool.friendly_name.lower()}"
            if "count" in res_dict:
                friendly_summary += f" ({res_dict['count']} items found)"
            elif "message" in res_dict and isinstance(res_dict["message"], str):
                friendly_summary = res_dict["message"]

            return ToolExecutionResult(
                tool_name=tool_name,
                status="completed",
                result_payload=res_dict,
                friendly_summary=friendly_summary,
                is_error=(res_dict.get("status") == "error"),
            )

        except asyncio.TimeoutError:
            logger.warning("[%s] Tool '%s' execution timed out after %.1fs", execution_id or "AGENT", tool_name, timeout)
            return ToolExecutionResult(
                tool_name=tool_name,
                status="failed",
                result_payload={"status": "error", "message": f"Tool '{tool_name}' timed out after {timeout} seconds."},
                friendly_summary=f"{tool.friendly_name} timed out",
                is_error=True,
            )
        except Exception as exc:
            logger.exception("[%s] Tool '%s' execution error: %s", execution_id or "AGENT", tool_name, exc)
            return ToolExecutionResult(
                tool_name=tool_name,
                status="failed",
                result_payload={"status": "error", "message": f"Tool execution failed: {str(exc)}"},
                friendly_summary=f"{tool.friendly_name} failed",
                is_error=True,
            )
