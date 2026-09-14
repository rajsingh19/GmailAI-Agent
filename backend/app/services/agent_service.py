"""
LLM Agent Service and Provider Abstraction.
Designed so underlying model provider (Gemini, OpenAI, Anthropic, Local) can be swapped seamlessly.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class LLMProvider(ABC):
    """Abstract Base Class for LLM Providers."""

    @abstractmethod
    async def generate_response(
        self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Execute LLM generation and return text response or function call specification."""
        pass


class GeminiProvider(LLMProvider):
    """Google Gemini API Provider implementation (Phase 5)."""

    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name

    async def generate_response(
        self, prompt: str, system_instruction: str, tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        raise NotImplementedError("Gemini integration will be activated in Phase 5")


class AgentService:
    """Agent orchestrator that routes user prompts through the selected LLM provider and handles tool execution."""

    def __init__(self, user_id: str, provider: LLMProvider):
        self.user_id = user_id
        self.provider = provider

    async def process_user_message(self, message: str) -> Dict[str, Any]:
        raise NotImplementedError("Agent dialogue pipeline will be activated in Phase 5")
