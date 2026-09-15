"""
Personal Knowledge & Semantic Retrieval AI Tools (Milestone 7).
Enables the AI Assistant to semantically search user's indexed personal data with strict user isolation.
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent.tool_registry import ToolRegistry, ToolDefinition, RiskLevel
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


async def execute_search_personal_knowledge(
    user_id: str,
    db: AsyncSession,
    query: str,
    source_type: Optional[str] = None,
    top_k: Optional[int] = 5,
) -> Dict[str, Any]:
    """
    Tool function for AI Agent to perform semantic search across the user's personal knowledge base.
    Strictly isolated to user_id. Returns untrusted context with backend citations.
    """
    service = RetrievalService()
    try:
        retrieval_res = await service.search_knowledge(
            db=db,
            user_id=user_id,
            query=query,
            source_type=source_type,
            top_k=top_k,
        )
        return retrieval_res
    except Exception as exc:
        logger.exception("Error executing search_personal_knowledge for user_id=%s: %s", user_id[:8], exc)
        return {
            "status": "error",
            "source": "personal_knowledge",
            "trusted": False,
            "message": f"Failed to retrieve personal knowledge: {str(exc)}",
            "results": [],
            "citations": [],
            "formatted_context": "An error occurred while searching your knowledge base.",
        }


def register_knowledge_tools() -> None:
    """Registers personal knowledge retrieval tools in the static ToolRegistry."""
    ToolRegistry.register(
        ToolDefinition(
            name="search_personal_knowledge",
            description=(
                "Semantically search your personal knowledge base (emails, calendar events, tasks, reminders) "
                "to answer questions about past discussions, deadlines, projects, or notes. "
                "Returns relevant excerpts with citation metadata."
            ),
            friendly_name="Searching personal knowledge",
            risk_level=RiskLevel.READ,
            func=execute_search_personal_knowledge,
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query to find relevant personal context.",
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Optional filter: 'gmail', 'calendar', 'task', or 'reminder'.",
                        "enum": ["gmail", "calendar", "task", "reminder"],
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of relevant excerpts to return (1-10). Defaults to 5.",
                    },
                },
                "required": ["query"],
            },
        )
    )
