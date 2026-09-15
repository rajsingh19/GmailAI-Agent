import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
import httpx

from app.ai.providers.base import (
    LLMProvider,
    LLMMessage,
    LLMToolDeclaration,
    LLMToolCall,
    LLMResponse,
    LLMProviderError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMInvalidResponseError,
)

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """
    Google Gemini API provider implementation via async HTTP REST requests.
    Supports function calling, multi-turn dialogue, and custom system instructions.
    Model-agnostic: model name is passed at initialization or dynamically configured.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model_name = model_name

    def _convert_schema_to_gemini(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cleans and normalizes JSON Schema into the subset supported by Gemini OpenAPI function declarations.
        Removes titles, extra metadata, and unsupported keys.
        """
        gemini_schema: Dict[str, Any] = {}

        schema_type = schema.get("type", "object")
        gemini_schema["type"] = schema_type

        if "description" in schema:
            gemini_schema["description"] = schema["description"]

        if schema_type == "object":
            properties = schema.get("properties", {})
            gemini_props = {}
            for prop_name, prop_def in properties.items():
                gemini_props[prop_name] = self._convert_schema_to_gemini(prop_def)
            gemini_schema["properties"] = gemini_props

            if "required" in schema:
                gemini_schema["required"] = schema["required"]

        elif schema_type == "array":
            items = schema.get("items", {})
            gemini_schema["items"] = self._convert_schema_to_gemini(items)

        if "enum" in schema:
            gemini_schema["enum"] = schema["enum"]

        return gemini_schema

    def _build_tools_payload(self, tools: Optional[List[LLMToolDeclaration]]) -> Optional[List[Dict[str, Any]]]:
        """Converts LLMToolDeclarations into Gemini tools payload."""
        if not tools:
            return None

        function_declarations = []
        for tool in tools:
            decl = {
                "name": tool.name,
                "description": tool.description,
                "parameters": self._convert_schema_to_gemini(tool.parameters),
            }
            function_declarations.append(decl)

        return [{"functionDeclarations": function_declarations}]

    def _build_contents_payload(self, messages: List[LLMMessage]) -> List[Dict[str, Any]]:
        """Converts normalized LLMMessages into Gemini contents structure."""
        contents = []

        for msg in messages:
            gemini_role = "user" if msg.role in ("user", "tool") else "model"
            parts: List[Dict[str, Any]] = []

            if msg.role == "tool" and msg.tool_name and msg.tool_response is not None:
                # Function response part
                parts.append({
                    "functionResponse": {
                        "name": msg.tool_name,
                        "response": {
                            "name": msg.tool_name,
                            "content": msg.tool_response,
                        },
                    }
                })
            elif msg.tool_calls:
                # Model function calls
                for tc in msg.tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments,
                        }
                    })
                if msg.content:
                    parts.append({"text": msg.content})
            elif msg.content:
                parts.append({"text": msg.content})

            if parts:
                contents.append({"role": gemini_role, "parts": parts})

        return contents

    async def generate_response(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMToolDeclaration]] = None,
        system_instruction: Optional[str] = None,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """
        Executes generation against Gemini REST API with tools and system instruction.
        """
        if not self.api_key:
            raise LLMAuthenticationError("GEMINI_API_KEY is missing or empty. Please set it in backend configuration.")

        url = f"{self.BASE_URL}/models/{self.model_name}:generateContent"
        params = {"key": self.api_key}

        payload: Dict[str, Any] = {
            "contents": self._build_contents_payload(messages),
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        tools_payload = self._build_tools_payload(tools)
        if tools_payload:
            payload["tools"] = tools_payload

        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, params=params, json=payload, headers=headers)

            if response.status_code == 401 or response.status_code == 403:
                raise LLMAuthenticationError(f"Gemini API authentication failed (HTTP {response.status_code}).")

            if response.status_code == 429:
                raise LLMRateLimitError("Gemini API rate limit or quota exceeded.")

            if response.status_code != 200:
                err_text = response.text[:200]
                logger.warning("Gemini API error (HTTP %d): %s", response.status_code, err_text)
                raise LLMProviderError(f"Gemini API returned error HTTP {response.status_code}.")

            data = response.json()
            return self._parse_gemini_response(data)

        except httpx.TimeoutException as exc:
            logger.warning("Gemini API request timed out after %.1f seconds", timeout)
            raise LLMTimeoutError(f"Gemini request timed out after {timeout} seconds.") from exc
        except (LLMProviderError, LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError):
            raise
        except Exception as exc:
            logger.exception("Unexpected error communicating with Gemini API: %s", exc)
            raise LLMProviderError(f"Failed to communicate with Gemini API: {exc}") from exc

    def _parse_gemini_response(self, data: Dict[str, Any]) -> LLMResponse:
        """Parses raw Gemini JSON response into standardized LLMResponse."""
        candidates = data.get("candidates", [])
        if not candidates:
            raise LLMInvalidResponseError("Gemini returned empty candidates list.")

        first_cand = candidates[0]
        content_obj = first_cand.get("content", {})
        parts = content_obj.get("parts", [])

        text_pieces: List[str] = []
        tool_calls: List[LLMToolCall] = []

        for idx, part in enumerate(parts):
            if "text" in part and part["text"]:
                text_pieces.append(part["text"])

            if "functionCall" in part:
                fc = part["functionCall"]
                name = fc.get("name", "")
                args = fc.get("args", {})
                call_id = f"call_{name}_{idx}"
                tool_calls.append(LLMToolCall(id=call_id, name=name, arguments=args))

        combined_text = "\n".join(text_pieces).strip() if text_pieces else None
        return LLMResponse(content=combined_text, tool_calls=tool_calls, raw_response=data)
