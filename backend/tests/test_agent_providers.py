"""
Unit tests for GeminiProvider and Base LLMProvider (Milestone 6).
Verifies:
- Model-agnostic initialization and configuration
- LLMMessage translation to Gemini REST API payload
- Tool definition conversion to Gemini functionDeclarations
- Function call extraction from Gemini candidate responses
- Error handling: HTTP 401/403 -> LLMAuthenticationError
- Error handling: HTTP 429 -> LLMRateLimitError
- Error handling: HTTP 504/Timeout -> LLMTimeoutError
- Error handling: Malformed response -> LLMInvalidResponseError
"""

import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from app.ai.providers.base import (
    LLMMessage,
    LLMToolDeclaration,
    LLMToolCall,
    LLMResponse,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMInvalidResponseError,
    LLMServiceUnavailableError,
)
from app.ai.providers.gemini_provider import GeminiProvider


@pytest.fixture
def gemini_provider():
    return GeminiProvider(api_key="test-api-key", model_name="gemini-3.5-flash")


def test_gemini_provider_init(gemini_provider):
    assert gemini_provider.api_key == "test-api-key"
    assert gemini_provider.model_name == "gemini-3.5-flash"


def test_convert_messages_to_gemini_contents(gemini_provider):
    messages = [
        LLMMessage(role="user", content="Hello"),
        LLMMessage(role="model", content="Hi there!"),
        LLMMessage(
            role="model",
            content="",
            tool_calls=[LLMToolCall(id="call_1", name="list_tasks", arguments={"limit": 5})],
        ),
        LLMMessage(
            role="tool",
            tool_name="list_tasks",
            tool_response={"tasks": []},
        ),
    ]

    contents = gemini_provider._build_contents_payload(messages)
    # Consecutive model turns are merged into a single turn with both parts
    assert len(contents) == 3
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"][0]["text"] == "Hello"
    assert contents[1]["role"] == "model"
    assert len(contents[1]["parts"]) == 2
    assert contents[1]["parts"][0]["text"] == "Hi there!"
    assert "functionCall" in contents[1]["parts"][1]
    assert contents[1]["parts"][1]["functionCall"]["name"] == "list_tasks"
    assert contents[2]["role"] == "user"
    assert "functionResponse" in contents[2]["parts"][0]
    assert contents[2]["parts"][0]["functionResponse"]["name"] == "list_tasks"


def test_convert_tools_to_gemini_declarations(gemini_provider):
    tools = [
        LLMToolDeclaration(
            name="create_task",
            description="Create a task",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title"},
                },
                "required": ["title"],
            },
        )
    ]

    declarations = gemini_provider._build_tools_payload(tools)
    assert declarations is not None
    assert len(declarations) == 1
    assert "functionDeclarations" in declarations[0]
    func_decl = declarations[0]["functionDeclarations"][0]
    assert func_decl["name"] == "create_task"
    assert func_decl["description"] == "Create a task"
    assert func_decl["parameters"]["properties"]["title"]["type"] == "string"


@pytest.mark.asyncio
async def test_generate_response_text_success(gemini_provider):
    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Hello! How can I help you today?"}],
                },
                "finishReason": "STOP",
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        response = await gemini_provider.generate_response(
            messages=[LLMMessage(role="user", content="Hello")]
        )

        assert isinstance(response, LLMResponse)
        assert response.content == "Hello! How can I help you today?"
        assert len(response.tool_calls) == 0


@pytest.mark.asyncio
async def test_generate_response_tool_calls_success(gemini_provider):
    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "list_tasks",
                                "args": {"limit": 10},
                            }
                        }
                    ],
                },
                "finishReason": "STOP",
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        response = await gemini_provider.generate_response(
            messages=[LLMMessage(role="user", content="Show my tasks")]
        )

        assert isinstance(response, LLMResponse)
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "list_tasks"
        assert response.tool_calls[0].arguments == {"limit": 10}


@pytest.mark.asyncio
async def test_gemini_provider_auth_error_401(gemini_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Invalid API Key"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(LLMAuthenticationError):
            await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )


@pytest.mark.asyncio
async def test_gemini_provider_auth_error_403(gemini_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Permission Denied"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(LLMAuthenticationError):
            await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )


@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_retry_with_retry_after_success(gemini_provider):
    """Verify HTTP 429 with Retry-After header retries and succeeds on subsequent attempt."""
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.headers = {"Retry-After": "0.01"}
    mock_429.text = "Rate limited"

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Recovered after retry!"}],
                },
                "finishReason": "STOP",
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_429, mock_200]
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            response = await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )
            assert response.content == "Recovered after retry!"
            assert mock_post.call_count == 2
            assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_retry_exponential_backoff_success(gemini_provider):
    """Verify HTTP 429 without Retry-After header uses exponential backoff and succeeds."""
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.headers = {}
    mock_429.text = "Quota exceeded"

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Success on retry 2"}],
                },
                "finishReason": "STOP",
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_429, mock_200]
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            response = await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )
            assert response.content == "Success on retry 2"
            assert mock_post.call_count == 2
            assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_exhausted_raises_error(gemini_provider):
    """Verify HTTP 429 is retried up to MAX_429_RETRIES (2 retries = 3 attempts total) then raises LLMRateLimitError."""
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.headers = {"Retry-After": "0.01"}
    mock_429.text = "Resource exhausted"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_429
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMRateLimitError):
                await gemini_provider.generate_response(
                    messages=[LLMMessage(role="user", content="Hi")]
                )
            assert mock_post.call_count == 3  # 1 initial + 2 retries
            assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_gemini_provider_400_not_retried(gemini_provider):
    """Verify HTTP 400 Bad Request is NOT retried."""
    from app.ai.providers.base import LLMProviderError
    mock_400 = MagicMock()
    mock_400.status_code = 400
    mock_400.text = "Bad Request"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_400
        with pytest.raises(LLMProviderError):
            await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_gemini_provider_404_not_retried(gemini_provider):
    """Verify HTTP 404 Not Found is NOT retried."""
    from app.ai.providers.base import LLMProviderError
    mock_404 = MagicMock()
    mock_404.status_code = 404
    mock_404.text = "Model not found"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_404
        with pytest.raises(LLMProviderError):
            await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_gemini_provider_auth_error_not_retried(gemini_provider):
    """Verify HTTP 401 is NOT retried."""
    mock_401 = MagicMock()
    mock_401.status_code = 401
    mock_401.text = "Unauthorized"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_401
        with pytest.raises(LLMAuthenticationError):
            await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )
        assert mock_post.call_count == 1


@pytest.mark.asyncio
async def test_gemini_provider_timeout_error(gemini_provider):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")
        with pytest.raises(LLMTimeoutError):
            await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )


@pytest.mark.asyncio
async def test_gemini_provider_invalid_response_format(gemini_provider):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"unexpected_key": "no candidates here"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(LLMInvalidResponseError):
            await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )


@pytest.mark.asyncio
async def test_gemini_provider_missing_api_key_raises_auth_error():
    provider = GeminiProvider(api_key="", model_name="gemini-2.0-flash")
    with pytest.raises(LLMAuthenticationError) as exc_info:
        await provider.generate_response(messages=[LLMMessage(role="user", content="Hi")])
    assert "missing or empty" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_gemini_provider_503_retry_success(gemini_provider):
    """Verify HTTP 503 is retried and succeeds on retry."""
    mock_503 = MagicMock()
    mock_503.status_code = 503
    mock_503.headers = {"Retry-After": "0.01"}
    mock_503.text = json.dumps({"error": {"code": 503, "message": "High demand"}})

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Success after 503"}],
                },
                "finishReason": "STOP",
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_503, mock_200]
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            response = await gemini_provider.generate_response(
                messages=[LLMMessage(role="user", content="Hi")]
            )
            assert response.content == "Success after 503"
            assert mock_post.call_count == 2
            assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_gemini_provider_503_exhausted_raises_service_unavailable(gemini_provider):
    """Verify repeated HTTP 503 exhausts 2 retries (3 attempts total) and raises LLMServiceUnavailableError."""
    mock_503 = MagicMock()
    mock_503.status_code = 503
    mock_503.headers = {"Retry-After": "0.01"}
    mock_503.text = json.dumps({"error": {"code": 503, "message": "High demand"}})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_503
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMServiceUnavailableError) as exc_info:
                await gemini_provider.generate_response(
                    messages=[LLMMessage(role="user", content="Hi")]
                )
            assert "high demand" in str(exc_info.value).lower() or "503" in str(exc_info.value)
            assert mock_post.call_count == 3  # 1 initial + 2 retries
            assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_gemini_provider_503_delay_exceeds_ceiling_fast_fails(gemini_provider):
    """Verify that when server requests delay exceeding ceiling, it fast-fails immediately without waiting."""
    mock_503 = MagicMock()
    mock_503.status_code = 503
    mock_503.headers = {"Retry-After": "120"}  # Exceeds MAX_BACKOFF_SECONDS (40s)
    mock_503.text = "High demand"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_503
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMServiceUnavailableError) as exc_info:
                await gemini_provider.generate_response(
                    messages=[LLMMessage(role="user", content="Hi")]
                )
            assert exc_info.value.retry_after == 120.0
            assert mock_post.call_count == 1  # Fast fails on first attempt
            assert mock_sleep.call_count == 0


@pytest.mark.asyncio
async def test_gemini_provider_system_instruction_inclusion(gemini_provider):
    mock_response_data = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Hello, I will obey system instructions."}],
                },
                "finishReason": "STOP",
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        resp = await gemini_provider.generate_response(
            messages=[LLMMessage(role="user", content="Hi")],
            system_instruction="You are a helpful assistant."
        )
        assert resp.content == "Hello, I will obey system instructions."
        # Verify systemInstruction was sent in payload
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        assert "systemInstruction" in payload
        assert payload["systemInstruction"]["parts"][0]["text"] == "You are a helpful assistant."

