"""Minimal async client for Groq's OpenAI-compatible chat completions API.

Used instead of LangChain so the app only needs pure-Python packages and can be bundled into an Android APK.
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import httpx
import structlog
from django.conf import settings

from app.services.app_settings import aget_value

logger = structlog.get_logger(__name__)


class GroqError(RuntimeError):
    """Raised when the Groq API returns an error or is not configured."""


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
            raise GroqError(message)

        return response.json()["choices"][0]["message"]
