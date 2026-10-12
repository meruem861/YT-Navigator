"""Chat model providers (Groq, Google Gemini, Anthropic Claude) behind one small async interface.

All clients take and return OpenAI-style messages so the agent code doesn't depend on the provider:
    pick_model(kind)  -> model id for "instant" (routing, small talk) or "powerful" (tool calling) replies
    chat(model, messages, tools=None, json_mode=False) -> {"role": "assistant", "content": str, "tool_calls"?: [...]}
    list_models()     -> model ids available to the key (also used by "Test keys")

Only plain HTTP (httpx) is used: the official SDKs depend on native packages (pydantic-core) that cannot be bundled
into the Android app.
"""

import asyncio
import json
import re
import time
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

import httpx
import structlog
from django.conf import settings

from app.services.app_settings import aget_value

logger = structlog.get_logger(__name__)

PROVIDERS = {"groq": "Groq", "gemini": "Google Gemini", "claude": "Anthropic Claude"}
PROVIDER_KEYS = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}

MODELS_CACHE_SECONDS = 3600
MAX_RETRIES = 2
NO_TOOLS_REMINDER = "Do not call any tool or function. Reply directly with the requested content."
_models_cache: Dict[Tuple[str, str], Tuple[float, List[str]]] = {}


class LLMError(RuntimeError):
    """Raised when a chat provider returns an error or is not configured."""


# Kept for backward compatibility with code and tests written for the Groq-only version
GroqError = LLMError


def choose_model(available: List[str], forced: str, candidates: List[str], markers=(), excluded=()) -> Optional[str]:
    """Pick the forced model, else the first available candidate, else an available model matching the markers."""
    for model in ([forced] if forced else []) + list(candidates):
        if model in available:
            return model
    # Newest first (version numbers sort ascending)
    usable = [m for m in sorted(available, reverse=True) if not any(x in m.lower() for x in excluded)]
    for marker in markers:
        matching = [m for m in usable if marker in m.lower()]
        if matching:
            return matching[0]
    return usable[0] if usable else None


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, list):
            data = data[0]
        error = data.get("error", data)
        return error.get("message") if isinstance(error, dict) else str(error)
    except Exception:
        return response.text[:300]


class BaseChatClient:
    """Shared model selection and key lookup."""

    provider = ""
    key_name = ""

    def __init__(self, timeout: float = 120.0):
        """Initialize the client.

        Args:
            timeout: Request timeout in seconds.
        """
        self.timeout = timeout

    async def api_key(self) -> str:
        """Return the key for this provider (user's key from Settings, else the built-in one)."""
        key = await aget_value(self.key_name)
        if not key:
            raise LLMError(f"No {PROVIDERS[self.provider]} API key set. Add one in Settings.")
        return key

    async def list_models(self) -> List[str]:  # pragma: no cover - implemented by subclasses
        """Return the model ids available to the key."""
        raise NotImplementedError

    def _choose(self, kind: str, available: List[str]) -> Optional[str]:  # pragma: no cover - subclasses
        raise NotImplementedError

    async def pick_model(self, kind: str) -> str:
        """Return the model to use for "instant" (routing, small talk) or "powerful" (tool calling) replies."""
        cache_key = (self.provider, await self.api_key())
        cached = _models_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < MODELS_CACHE_SECONDS:
            available = cached[1]
        else:
            available = await self.list_models()
            _models_cache[cache_key] = (time.monotonic(), available)
        model = self._choose(kind, available)
        if not model:
            raise LLMError(f"No chat model is available for this {PROVIDERS[self.provider]} key.")
        return model


class OpenAICompatibleClient(BaseChatClient):
    """Client for OpenAI-compatible chat completion APIs (Groq, Gemini's OpenAI endpoint)."""

    base_url_setting = ""

    @property
    def base_url(self) -> str:
        """API base URL."""
        return getattr(settings, self.base_url_setting).rstrip("/")

    async def list_models(self) -> List[str]:
        """Return the model ids available to the key."""
        api_key = await self.api_key()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
        if response.status_code != 200:
            raise LLMError(_error_message(response))
        # Gemini lists ids as "models/gemini-..."; requests use the bare id
        return [m["id"].removeprefix("models/") for m in response.json().get("data", [])]

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """Send a chat completion request and return the assistant message."""
        api_key = await self.api_key()
        payload: Dict[str, Any] = {"model": model, "messages": list(messages), "temperature": temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(MAX_RETRIES + 1):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )
            if response.status_code == 200:
                message = response.json()["choices"][0]["message"]
                return {k: v for k, v in message.items() if v is not None}

            message = _error_message(response)
            logger.error(
                "Chat API error",
                provider=self.provider,
                status_code=response.status_code,
                error=message,
                attempt=attempt + 1,
            )
            if attempt == MAX_RETRIES:
                break

            if "called a tool" in message and not tools:
                # Some models (e.g. gpt-oss) try to call a tool when none is offered: ask again, explicitly
                payload["messages"] = payload["messages"] + [{"role": "system", "content": NO_TOOLS_REMINDER}]
                payload["temperature"] = 0.3
            elif response.status_code == 429:
                # Rate limit: the message often says how long to wait ("Please try again in 1m2.5s")
                match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", message)
                wait = (int(match.group(1) or 0) * 60 + float(match.group(2))) if match else 5.0
                if wait > 30:
                    break
                await asyncio.sleep(wait + 0.5)
            elif response.status_code >= 500:
                await asyncio.sleep(2)
            else:
                break

        if response.status_code == 404 or "does not exist" in message or "decommissioned" in message:
            # The model may have been retired: list the models again next time
            _models_cache.clear()
        raise LLMError(message)


class GroqClient(OpenAICompatibleClient):
    """Groq (free tier available)."""

    provider = "groq"
    key_name = "GROQ_API_KEY"
    base_url_setting = "GROQ_API_URL"

    def _choose(self, kind: str, available: List[str]) -> Optional[str]:
        excluded = ("whisper", "tts", "guard", "playai", "orpheus", "distil", "compound", "allam")
        if kind == "instant":
            return choose_model(available, settings.INSTANT_LLM, settings.INSTANT_LLM_CANDIDATES, excluded=excluded)
        return choose_model(available, settings.POWERFUL_LLM, settings.POWERFUL_LLM_CANDIDATES, excluded=excluded)


class GeminiClient(OpenAICompatibleClient):
    """Google Gemini through its OpenAI-compatible endpoint (free tier available)."""

    provider = "gemini"
    key_name = "GEMINI_API_KEY"
    base_url_setting = "GEMINI_API_URL"

    def _choose(self, kind: str, available: List[str]) -> Optional[str]:
        chat_models = [m for m in available if m.startswith("gemini")]
        excluded = ("embedding", "image", "tts", "audio", "live", "vision", "lite", "exp", "learnlm")
        if kind == "instant":
            return choose_model(
                chat_models, settings.GEMINI_INSTANT_LLM, settings.GEMINI_INSTANT_CANDIDATES, ("flash",), excluded
            )
        return choose_model(
            chat_models, settings.GEMINI_POWERFUL_LLM, settings.GEMINI_POWERFUL_CANDIDATES, ("flash", "pro"), excluded
        )


class ClaudeClient(BaseChatClient):
    """Anthropic Claude through the Messages API (paid; best answer quality).

    Messages are converted from/to the OpenAI shape used by the agent. The assistant's original content blocks
    (including thinking blocks) are kept in "_claude_content" and sent back unchanged during the tool loop.
    """

    provider = "claude"
    key_name = "ANTHROPIC_API_KEY"
    api_version = "2023-06-01"
    fallback_beta = "server-side-fallback-2026-07-01"

    def _headers(self, api_key: str) -> Dict[str, str]:
        return {"x-api-key": api_key, "anthropic-version": self.api_version, "content-type": "application/json"}

    async def list_models(self) -> List[str]:
        """Return the model ids available to the key."""
        api_key = await self.api_key()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{settings.ANTHROPIC_API_URL.rstrip('/')}/models",
                params={"limit": 100},
                headers=self._headers(api_key),
            )
        if response.status_code != 200:
            raise LLMError(_error_message(response))
        return [m["id"] for m in response.json().get("data", [])]

    def _choose(self, kind: str, available: List[str]) -> Optional[str]:
        model = settings.CLAUDE_INSTANT_LLM if kind == "instant" else settings.CLAUDE_POWERFUL_LLM
        # Keys normally see every model; if the listing is incomplete, use the configured model anyway
        return model if not available or model in available else choose_model(available, model, [], ("claude",))

    @staticmethod
    def to_claude(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """Convert OpenAI-style messages to (system prompt, Claude messages)."""
        system_parts, converted = [], []
        for message in messages:
            role = message["role"]
            if role == "system":
                if converted:
                    converted.append({"role": "user", "content": message["content"]})
                else:
                    system_parts.append(message["content"])
            elif role == "user":
                converted.append({"role": "user", "content": message["content"]})
            elif role == "assistant":
                content = message.get("_claude_content")
                if content is None:
                    content = message.get("content") or ""
                    if not content:
                        continue
                converted.append({"role": "assistant", "content": content})
            elif role == "tool":
                result = {"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}
                previous = converted[-1] if converted else None
                if previous and previous["role"] == "user" and isinstance(previous["content"], list):
                    # All results of one assistant turn go in a single user message
                    previous["content"].append(result)
                else:
                    converted.append({"role": "user", "content": [result]})
        # The conversation must start with the user
        while converted and converted[0]["role"] != "user":
            converted.pop(0)
        return "\n\n".join(system_parts), converted

    @staticmethod
    def to_claude_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI function definitions to Claude tool definitions."""
        return [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "input_schema": tool["function"]["parameters"],
            }
            for tool in tools
        ]

    @staticmethod
    def from_claude(data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a Claude response to an OpenAI-style assistant message."""
        content = data.get("content", [])
        if data.get("stop_reason") == "refusal":
            return {"role": "assistant", "content": "I can't help with that request."}
        text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        message: Dict[str, Any] = {"role": "assistant", "content": text, "_claude_content": content}
        tool_calls = [
            {
                "id": block["id"],
                "type": "function",
                "function": {"name": block["name"], "arguments": json.dumps(block.get("input", {}))},
            }
            for block in content
            if block.get("type") == "tool_use"
        ]
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """Send a Messages API request and return an OpenAI-style assistant message."""
        api_key = await self.api_key()
        system, claude_messages = self.to_claude(messages)
        payload: Dict[str, Any] = {"model": model, "max_tokens": 16000, "messages": claude_messages}
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self.to_claude_tools(tools)
        headers = self._headers(api_key)
        if model == settings.CLAUDE_POWERFUL_LLM:
            # If the model declines a request, Anthropic re-runs it on a suitable fallback model
            payload["fallbacks"] = "default"
            headers["anthropic-beta"] = self.fallback_beta

        for attempt in range(MAX_RETRIES + 1):
            async with httpx.AsyncClient(timeout=max(self.timeout, 300)) as client:
                response = await client.post(
                    f"{settings.ANTHROPIC_API_URL.rstrip('/')}/messages", json=payload, headers=headers
                )
            if response.status_code == 200:
                return self.from_claude(response.json())
            message = _error_message(response)
            logger.error("Claude API error", status_code=response.status_code, error=message, attempt=attempt + 1)
            if attempt == MAX_RETRIES or response.status_code not in (429, 500, 502, 503, 529):
                break
            try:
                wait = float(response.headers.get("retry-after", 5))
            except ValueError:
                wait = 5
            if wait > 30:
                break
            await asyncio.sleep(wait)
        raise LLMError(message)


CLIENTS = {"groq": GroqClient, "gemini": GeminiClient, "claude": ClaudeClient}


async def get_provider() -> str:
    """Return the chat provider selected in Settings."""
    provider = await aget_value("CHAT_PROVIDER")
    return provider if provider in CLIENTS else "groq"


async def get_chat_client() -> BaseChatClient:
    """Return a client for the chat provider selected in Settings."""
    return CLIENTS[await get_provider()]()
