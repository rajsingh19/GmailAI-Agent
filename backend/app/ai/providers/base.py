from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


class LLMProviderError(Exception):
    """Base exception for all LLM provider communication and generation errors."""
    pass


class LLMAuthenticationError(LLMProviderError):
    """Raised when the LLM provider API key or credentials are invalid."""
    pass


class LLMRateLimitError(LLMProviderError):
    """Raised when the LLM provider returns a 429 / quota exceeded error."""
    pass


class LLMTimeoutError(LLMProviderError):
    """Raised when the LLM provider call exceeds the configured timeout."""
    pass


class LLMInvalidResponseError(LLMProviderError):
    """Raised when the LLM provider returns an unparseable or malformed response."""
    pass


@dataclass
class LLMToolCall:
    """Represents a tool execution request returned by the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMToolDeclaration:
    """Represents a tool specification provided to the LLM."""
    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass
class LLMMessage:
    """Represents a message in the conversational context."""
    role: str  # "user", "model", "system", "tool"
    content: Optional[str] = None
    tool_calls: Optional[List[LLMToolCall]] = None
    tool_name: Optional[str] = None
    tool_response: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    """Normalized response returned from an LLM provider."""
    content: Optional[str] = None
    tool_calls: List[LLMToolCall] = field(default_factory=list)
    raw_response: Optional[Dict[str, Any]] = None


class LLMProvider(ABC):
    """
    Abstract provider interface for Language Model integrations.
    Allows seamless swapping of model engines (Gemini, Anthropic, OpenAI, Local)
    without affecting orchestrator logic.
    """

    @abstractmethod
    async def generate_response(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMToolDeclaration]] = None,
        system_instruction: Optional[str] = None,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """
        Sends the dialogue history and available tools to the LLM and returns
        a normalized response containing text and/or tool execution requests.
        """
        pass
