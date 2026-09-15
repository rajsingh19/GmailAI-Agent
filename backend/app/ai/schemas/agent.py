from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class AgentChatMessage(BaseModel):
    """Sanitized conversational message for context."""
    role: Literal["user", "assistant"] = Field(..., description="Role of the speaker (user or assistant)")
    content: str = Field(..., min_length=1, max_length=4000, description="Message content")


class AgentChatRequest(BaseModel):
    """Incoming user chat request to the AI Agent."""
    message: str = Field(..., min_length=1, max_length=4000, description="User's natural language instruction or query")
    history: Optional[List[AgentChatMessage]] = Field(default=None, description="Recent conversation history")
    confirmation_token: Optional[str] = Field(default=None, description="One-time server-issued confirmation token for high-risk actions")


class ToolActivityInfo(BaseModel):
    """Sanitized, user-friendly summary of an executed tool call."""
    name: str = Field(..., description="Friendly tool name (e.g., 'Searching Gmail', 'Listing tasks')")
    status: Literal["running", "completed", "failed", "confirmation_required"] = Field(..., description="Execution status")
    summary: str = Field(..., description="Safe human-readable summary of what was done")


class ConfirmationChallenge(BaseModel):
    """Structured challenge presented when a high-risk tool requires explicit user confirmation."""
    status: Literal["confirmation_required"] = "confirmation_required"
    tool: str = Field(..., description="Target tool name requiring confirmation (e.g. 'delete_task')")
    target_id: str = Field(..., description="Target resource ID (e.g. task ID or reminder ID)")
    action: str = Field(..., description="Intended action description (e.g. 'delete')")
    confirmation_token: str = Field(..., description="Cryptographically signed, single-use token to return with confirmed request")
    message: str = Field(..., description="User-friendly explanation of why confirmation is needed")


class AgentChatResponse(BaseModel):
    """Response returned from the AI Agent orchestrator."""
    message: str = Field(..., description="Assistant's synthesized textual answer")
    execution_id: str = Field(..., description="Unique execution UUID for auditability and tracing")
    tool_activities: List[ToolActivityInfo] = Field(default_factory=list, description="Sanitized list of tools utilized")
    confirmation_required: Optional[ConfirmationChallenge] = Field(default=None, description="Populated if a high-risk action requires confirmation")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution telemetry (model name, duration ms, tool count)")


class ToolDefinitionSchema(BaseModel):
    """Schema returned by GET /api/v1/agent/tools."""
    name: str
    description: str
    risk_level: str
    parameters: Dict[str, Any]


class AgentToolsResponse(BaseModel):
    tools: List[ToolDefinitionSchema]
    total: int
