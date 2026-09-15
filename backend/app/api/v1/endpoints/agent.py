import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.ai.agent.orchestrator import AgentOrchestrator
from app.ai.agent.tool_registry import ToolRegistry
from app.ai.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentToolsResponse,
    ToolDefinitionSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=AgentChatResponse)
async def chat_with_agent(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Primary conversational endpoint for the AI Assistant.
    Processes natural language requests and coordinates safe, user-isolated tool execution.
    """
    orchestrator = AgentOrchestrator()
    response = await orchestrator.process_message(
        user=current_user,
        db=db,
        message=request.message,
        history=request.history,
        confirmation_token=request.confirmation_token,
    )
    return response


@router.get("/tools", response_model=AgentToolsResponse)
async def list_available_tools(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the metadata of all registered and authorized tools available to the AI Agent.
    """
    tools = ToolRegistry.list_tools()
    schemas = [
        ToolDefinitionSchema(
            name=t.name,
            description=t.description,
            risk_level=t.risk_level.value,
            parameters=t.parameters_schema,
        )
        for t in tools
    ]
    return AgentToolsResponse(tools=schemas, total=len(schemas))
