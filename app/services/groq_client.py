"""Minimal async client for Groq's OpenAI-compatible chat completions API.

Used instead of LangChain so the app only needs pure-Python packages and can be bundled into an Android APK.
"""

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


class GroqError(RuntimeError):
    """Raised when the Groq API returns an error or is not configured."""


# Models that are not general chat models
NON_CHAT_MODEL_MARKERS = ("whisper", "tts", "guard", "playai", "orpheus", "distil", "compound", "allam")
MODELS_CACHE_SECONDS = 3600
_models_cache: Dict[str, Tuple[float, List[str]]] = {}


def choose_model(available: List[str], forced: str, candidates: List[str]) -> Optional[str]:
    """Pick the forced model, else the first available candidate, else any available chat model."""
    for model in ([forced] if forced else []) + list(candidates):
        if model in available:
            return model
    chat_models = [m for m in sorted(available) if not any(marker in m.lower() for marker in NON_CHAT_MODEL_MARKERS)]
    return chat_models[0] if chat_models else None


class GroqClient:
    """Async client for Groq chat completions (with tool calling)."""

    def __init__(self, timeout: float = 120.0):
        """Initialize the client.

        Args:
            timeout: Request timeout in seconds.
        """
        self.timeout = timeout

    async def list_models(self) -> List[str]:
        """Return the model ids available to the configured key (used to check the key in Settings)."""
        api_key = await aget_value("GROQ_API_KEY")
        if not api_key:
            raise GroqError("No Groq API key set.")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{settings.GROQ_API_URL.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}
            )
        if response.status_code != 200:
            try:
                message = response.json()["error"]["message"]
            except Exception:
                message = response.text[:300]
            raise GroqError(message)
        return [model["id"] for model in response.json().get("data", [])]

    async def pick_model(self, kind: str) -> str:
        """Return the model to use for "instant" (routing, small talk) or "powerful" (tool calling) replies."""
        api_key = await aget_value("GROQ_API_KEY")
        cached = _models_cache.get(api_key)
        if cached and time.monotonic() - cached[0] < MODELS_CACHE_SECONDS:
            available = cached[1]
        else:
            available = await self.list_models()
            _models_cache[api_key] = (time.monotonic(), available)

        if kind == "instant":
            model = choose_model(available, settings.INSTANT_LLM, settings.INSTANT_LLM_CANDIDATES)
        else:
            model = choose_model(available, settings.POWERFUL_LLM, settings.POWERFUL_LLM_CANDIDATES)
        if not model:
            raise GroqError("No chat model is available for this Groq key.")
        return model

    async def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """Send a chat completion request and return the assistant message.

        Args:
            model: Groq model name.
            messages: OpenAI-style messages.
            tools: OpenAI-style tool definitions.
            json_mode: Force the model to answer with a JSON object.
            temperature: Sampling temperature.

        Returns:
            dict: The assistant message ({"role", "content", "tool_calls"?}).
        """
        api_key = await aget_value("GROQ_API_KEY")
        if not api_key:
            raise GroqError("No Groq API key set. Add one in Settings.")

        payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{settings.GROQ_API_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )

        if response.status_code != 200:
            try:
                message = response.json()["error"]["message"]
            except Exception:
                message = response.text[:300]
            logger.error("Groq API error", status_code=response.status_code, error=message)
            if response.status_code == 404 or "model" in message.lower():
                # The model may have been retired: list the models again next time
                _models_cache.clear()
            raise GroqError(message)

        return response.json()["choices"][0]["message"]
