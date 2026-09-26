import asyncio
import json
import logging
import random
import re
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
    LLMDailyQuotaExhaustedError,
    LLMTimeoutError,
    LLMInvalidResponseError,
    LLMServiceUnavailableError,
)

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """
    Google Gemini API provider implementation via async HTTP REST requests.
    Supports function calling, multi-turn dialogue, and custom system instructions.
    Model-agnostic: model name is passed at initialization or dynamically configured.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    MAX_429_RETRIES = 2
    MAX_BACKOFF_SECONDS = 40.0
    FALLBACK_MODELS = []

    def __init__(self, api_key: str, model_name: str = "gemini-3.5-flash-lite", max_retries: int = 2, fallback_models: Optional[List[str]] = None):
        self.api_key = api_key
        self.model_name = model_name
        self.max_retries = max(0, min(max_retries, 2))  # Strictly bounded at 0-2 retries
        self.fallback_models = fallback_models or self.FALLBACK_MODELS

    def _parse_429_error(
        self, response: httpx.Response, attempt: int
    ) -> tuple[bool, Optional[str], Optional[str], Optional[float], Optional[float]]:
        """
        Parses HTTP 429 response details to distinguish daily quota exhaustion from temporary rate limits.
        Returns tuple of:
          (is_daily_quota, quota_metric, quota_limit, immediate_backoff_delay, server_raw_retry_after)
        """
        is_daily_quota = False
        quota_metric: Optional[str] = None
        quota_limit: Optional[str] = None
        server_raw_delay: Optional[float] = None

        # 1. Parse JSON error details from Google API
        try:
            data = response.json()
            error_obj = data.get("error", {})
            details = error_obj.get("details", [])

            for d in details:
                detail_type = d.get("@type", "")
                if detail_type == "type.googleapis.com/google.rpc.QuotaFailure":
                    for violation in d.get("violations", []):
                        desc = violation.get("description", "")
                        if any(kw in desc.lower() for kw in ["perday", "daily", "per day", "requestsperday"]):
                            is_daily_quota = True
                        if "quota metric" in desc.lower():
                            m = re.search(r"quota metric '([^']+)'", desc)
                            if m:
                                quota_metric = m.group(1)
                        if "limit '" in desc.lower():
                            l = re.search(r"limit '([^']+)'", desc)
                            if l:
                                quota_limit = l.group(1)
                elif detail_type == "type.googleapis.com/google.rpc.ErrorInfo":
                    meta = d.get("metadata", {})
                    qm = meta.get("quota_metric", "")
                    ql = meta.get("quota_limit", "")
                    if qm:
                        quota_metric = qm
                    if ql:
                        quota_limit = ql
                    if any(kw in (qm + " " + ql).lower() for kw in ["perday", "daily", "per day", "requestsperday"]):
                        is_daily_quota = True
                elif detail_type == "type.googleapis.com/google.rpc.RetryInfo":
                    rd = d.get("retryDelay", "")
                    match = re.search(r"([0-9\.]+)", rd)
                    if match:
                        server_raw_delay = float(match.group(1))

            msg = error_obj.get("message", "")
            if any(kw in msg.lower() for kw in ["perday", "daily", "per day", "requestsperday"]):
                is_daily_quota = True
        except Exception:
            pass

        # 2. Check raw response text if JSON didn't catch daily quota keyword
        if not is_daily_quota:
            raw_text = response.text.lower()
            if any(kw in raw_text for kw in ["perday", "daily", "per day", "requestsperday"]):
                is_daily_quota = True

        # 3. Check Retry-After header
        retry_after_header = response.headers.get("Retry-After")
        if retry_after_header and server_raw_delay is None:
            try:
                server_raw_delay = float(retry_after_header.strip())
            except ValueError:
                pass

        if server_raw_delay is None:
            match = re.search(r"retry in\s+([0-9\.]+)\s*s?", response.text, re.IGNORECASE)
            if match:
                server_raw_delay = float(match.group(1))

        if is_daily_quota:
            # For daily quota exhaustion, any short RetryInfo (e.g. 4s) is misleading and NOT a valid recovery delay
            return True, quota_metric, quota_limit, None, None

        immediate_delay: Optional[float] = None
        if server_raw_delay is not None:
            if 0 <= server_raw_delay <= self.MAX_BACKOFF_SECONDS:
                immediate_delay = server_raw_delay + random.uniform(0.05, 0.2)
            else:
                logger.info("Server requested retry delay of %.1fs which exceeds backoff limit.", server_raw_delay)
                immediate_delay = None
        else:
            base_delay = 1.0 * (2 ** attempt)
            jitter = random.uniform(0.1, 0.5)
            immediate_delay = min(base_delay + jitter, self.MAX_BACKOFF_SECONDS)

        return False, quota_metric, quota_limit, immediate_delay, server_raw_delay

    def _extract_retry_delay(self, response: httpx.Response, attempt: int) -> tuple[Optional[float], Optional[float]]:
        """
        Extracts backoff delay for transient HTTP 5xx responses.
        Returns tuple of (immediate_backoff_delay, server_raw_retry_after).
        """
        server_raw_delay: Optional[float] = None

        retry_after_header = response.headers.get("Retry-After")
        if retry_after_header:
            try:
                server_raw_delay = float(retry_after_header.strip())
            except ValueError:
                pass

        if server_raw_delay is None:
            try:
                data = response.json()
                details = data.get("error", {}).get("details", [])
                for d in details:
                    if d.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                        rd = d.get("retryDelay", "")
                        match = re.search(r"([0-9\.]+)", rd)
                        if match:
                            server_raw_delay = float(match.group(1))
                            break
            except Exception:
                pass

        if server_raw_delay is not None:
            if 0 <= server_raw_delay <= self.MAX_BACKOFF_SECONDS:
                return server_raw_delay + random.uniform(0.05, 0.2), server_raw_delay
            else:
                return None, server_raw_delay

        base_delay = 1.0 * (2 ** attempt)
        jitter = random.uniform(0.1, 0.5)
        total_delay = min(base_delay + jitter, self.MAX_BACKOFF_SECONDS)
        return total_delay, None

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
                # Model function calls - must preserve thoughtSignature / raw_part if provided
                for tc in msg.tool_calls:
                    if tc.raw_part:
                        parts.append(tc.raw_part)
                    else:
                        fc_dict: Dict[str, Any] = {
                            "functionCall": {
                                "name": tc.name,
                                "args": tc.arguments,
                            }
                        }
                        if tc.thought_signature:
                            fc_dict["thoughtSignature"] = tc.thought_signature
                        parts.append(fc_dict)
                if msg.content:
                    parts.append({"text": msg.content})
            elif msg.content:
                parts.append({"text": msg.content})

            if parts:
                if contents and contents[-1]["role"] == gemini_role:
                    contents[-1]["parts"].extend(parts)
                else:
                    contents.append({"role": gemini_role, "parts": parts})

        return contents

    async def generate_response(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[LLMToolDeclaration]] = None,
        system_instruction: Optional[str] = None,
        timeout: float = 30.0,
        generation_config: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Executes generation against Gemini REST API with tools and system instruction.
        Includes duration logging, bounded retries, and fallback to active flash models.
        """
        if not self.api_key:
            raise LLMAuthenticationError("GEMINI_API_KEY is missing or empty. Please set it in backend configuration.")

        active_models_to_try = [self.model_name]
        for fallback_m in self.fallback_models:
            if fallback_m not in active_models_to_try:
                active_models_to_try.append(fallback_m)

        last_exception: Optional[Exception] = None

        # Build effective generationConfig merging generation_config, temperature, max_tokens
        merged_gen_config = dict(generation_config or {})
        if temperature is not None:
            merged_gen_config["temperature"] = temperature
        if max_tokens is not None:
            merged_gen_config["maxOutputTokens"] = max_tokens

        for model_idx, current_model in enumerate(active_models_to_try):
            url = f"{self.BASE_URL}/models/{current_model}:generateContent"
            params = {"key": self.api_key}

            payload: Dict[str, Any] = {
                "contents": self._build_contents_payload(messages),
            }

            if system_instruction:
                payload["systemInstruction"] = {
                    "parts": [{"text": system_instruction}]
                }

            if merged_gen_config:
                payload["generationConfig"] = merged_gen_config

            tools_payload = self._build_tools_payload(tools)
            if tools_payload:
                payload["tools"] = tools_payload

            headers = {"Content-Type": "application/json"}

            attempt = 0
            while True:
                start_time = asyncio.get_event_loop().time()
                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(url, params=params, json=payload, headers=headers)

                    duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000

                    if response.status_code in (401, 403):
                        logger.warning("Gemini API authentication failed (HTTP %d) on model '%s' in %.1fms", response.status_code, current_model, duration_ms)
                        raise LLMAuthenticationError(f"Gemini API authentication failed (HTTP {response.status_code}).")

                    if response.status_code == 429:
                        is_daily, q_metric, q_limit, immediate_delay, server_delay = self._parse_429_error(response, attempt)
                        if is_daily:
                            logger.warning(
                                "Gemini daily quota exhausted on model '%s' (metric=%s, limit=%s). Not retrying.",
                                current_model,
                                q_metric,
                                q_limit,
                            )
                            raise LLMDailyQuotaExhaustedError(
                                message="Gemini daily quota exhausted. Smart Reply will work when your quota resets or you configure a billing-enabled plan.",
                                quota_metric=q_metric,
                                quota_limit=q_limit,
                            )

                        if attempt < self.max_retries and immediate_delay is not None:
                            logger.warning(
                                "Gemini API rate limited (HTTP 429) on model '%s'. Retrying attempt %d/%d after %.2fs backoff...",
                                current_model,
                                attempt + 1,
                                self.max_retries,
                                immediate_delay,
                            )
                            attempt += 1
                            await asyncio.sleep(immediate_delay)
                            continue

                        logger.warning("Gemini API rate limit exceeded on model '%s' after %d attempts.", current_model, attempt + 1)
                        raise LLMRateLimitError("Gemini API rate limit reached.", retry_after=server_delay)

                    if response.status_code in (500, 502, 503, 504):
                        logger.warning("Gemini API upstream error (HTTP %d) on model '%s' in %.1fms", response.status_code, current_model, duration_ms)
                        immediate_delay, server_delay = self._extract_retry_delay(response, attempt)
                        if attempt < self.max_retries and immediate_delay is not None:
                            attempt += 1
                            await asyncio.sleep(immediate_delay)
                            continue

                        if immediate_delay is None:
                            raise LLMServiceUnavailableError(
                                f"Gemini API is temporarily experiencing high demand (HTTP {response.status_code}).",
                                retry_after=server_delay,
                            )

                        if model_idx < len(active_models_to_try) - 1:
                            logger.info("Failing over from model '%s' to '%s' due to HTTP %d", current_model, active_models_to_try[model_idx + 1], response.status_code)
                            break

                        raise LLMServiceUnavailableError(
                            f"Gemini API is temporarily experiencing high demand (HTTP {response.status_code}).",
                            retry_after=server_delay,
                        )

                    if response.status_code != 200:
                        err_text = response.text[:200]
                        logger.warning("Gemini API error (HTTP %d) on model '%s' in %.1fms: %s", response.status_code, current_model, duration_ms, err_text)
                        raise LLMProviderError(f"Gemini API returned error HTTP {response.status_code}.")

                    logger.info("Gemini API request to model '%s' succeeded (HTTP 200) in %.1fms", current_model, duration_ms)
                    data = response.json()
                    return self._parse_gemini_response(data)

                except httpx.TimeoutException as exc:
                    duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                    logger.warning("Gemini API request to model '%s' timed out after %.1fms (timeout=%.1fs)", current_model, duration_ms, timeout)
                    if model_idx < len(active_models_to_try) - 1:
                        logger.info("Failing over from model '%s' to '%s' after timeout", current_model, active_models_to_try[model_idx + 1])
                        last_exception = exc
                        break
                    raise LLMTimeoutError(f"Gemini request timed out after {timeout} seconds.") from exc
                except (LLMProviderError, LLMAuthenticationError, LLMRateLimitError, LLMDailyQuotaExhaustedError, LLMTimeoutError, LLMServiceUnavailableError):
                    raise
                except Exception as exc:
                    duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                    logger.exception("Unexpected error communicating with Gemini API on model '%s' in %.1fms: %s", current_model, duration_ms, exc)
                    if model_idx < len(active_models_to_try) - 1:
                        last_exception = exc
                        break
                    raise LLMProviderError(f"Failed to communicate with Gemini API: {exc}") from exc

        if last_exception:
            raise LLMTimeoutError(f"Gemini request timed out after {timeout} seconds.") from last_exception

        raise LLMProviderError("Failed to generate response with available Gemini models.")

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
                thought_sig = part.get("thoughtSignature") or part.get("thought_signature")
                tool_calls.append(
                    LLMToolCall(
                        id=call_id,
                        name=name,
                        arguments=args,
                        thought_signature=thought_sig,
                        raw_part=part,
                    )
                )

        combined_text = "\n".join(text_pieces).strip() if text_pieces else None
        return LLMResponse(content=combined_text, tool_calls=tool_calls, raw_response=data)
