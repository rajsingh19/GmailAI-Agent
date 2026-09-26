from enum import Enum
from typing import Dict, Any, Callable, Optional, List
from pydantic import BaseModel

from app.ai.providers.base import LLMToolDeclaration


class RiskLevel(str, Enum):
    """Tool execution risk classification."""
    READ = "READ"                          # Automatic execution
    LOW_RISK_WRITE = "LOW_RISK_WRITE"      # Automatic execution for explicit user intent
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"    # Requires cryptographic confirmation token


class ToolDefinition(BaseModel):
    """Encapsulates a registered backend tool specification."""
    name: str
    description: str
    friendly_name: str
    parameters_schema: Dict[str, Any]
    risk_level: RiskLevel = RiskLevel.READ
    func: Optional[Any] = None  # Async callable (user_id, db, **kwargs)
    target_id_param: Optional[str] = None  # e.g. "task_id" or "reminder_id" for high-risk binding

    model_config = {"arbitrary_types_allowed": True}


class ToolRegistry:
    """
    Central static tool whitelist registry.
    Only tools registered in this registry can be selected or executed by the AI Agent.
    """

    _tools: Dict[str, ToolDefinition] = {}

    @classmethod
    def _ensure_initialized(cls) -> None:
        if not cls._tools:
            try:
                from app.ai.tools import register_all_tools
                register_all_tools()
            except ImportError:
                pass

    @classmethod
    def register(cls, tool: ToolDefinition) -> None:
        """Registers a tool in the static whitelist."""
        cls._tools[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> Optional[ToolDefinition]:
        """Retrieves a tool definition by name."""
        cls._ensure_initialized()
        return cls._tools.get(name)

    @classmethod
    def list_tools(cls) -> List[ToolDefinition]:
        """Returns all registered tool definitions."""
        cls._ensure_initialized()
        return list(cls._tools.values())

    @classmethod
    def get_tool_declarations(cls) -> List[LLMToolDeclaration]:
        """Converts registered tools into normalized declarations for LLM providers."""
        cls._ensure_initialized()
        declarations = []
        for tool in cls._tools.values():
            decl = LLMToolDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters_schema,
            )
            declarations.append(decl)
        return declarations

    @classmethod
    def clear_for_testing(cls) -> None:
        """Helper for test suites."""
        cls._tools.clear()
