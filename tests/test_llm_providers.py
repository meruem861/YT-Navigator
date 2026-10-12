"""Tests for the Gemini and Claude providers (HTTP is faked)."""

import json

import httpx
import pytest

from app.services import llm_client
from app.services.llm_client import (
    ClaudeClient,
    GeminiClient,
)


def test_claude_message_conversion_round_trip():
    tool_use = {"type": "tool_use", "id": "tu1", "name": "execute_query", "input": {"query": "SELECT 1"}}
    reply = ClaudeClient.from_claude(
        {
            "content": [
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "text", "text": "Let me check."},
                tool_use,
            ],
            "stop_reason": "tool_use",
        }
    )
    assert reply["content"] == "Let me check."
    assert reply["tool_calls"][0]["function"] == {"name": "execute_query", "arguments": '{"query": "SELECT 1"}'}

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "assistant", "content": "older answer without a user turn before"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "Let me check.",
            "tool_calls": reply["tool_calls"],
            "_claude_content": reply["_claude_content"],
        },
        {"role": "tool", "tool_call_id": "tu1", "content": "result 1"},
        {"role": "tool", "tool_call_id": "tu2", "content": "result 2"},
    ]
    system, converted = ClaudeClient.to_claude(messages)
    assert system == "You are helpful."
    assert [m["role"] for m in converted] == ["user", "assistant", "user"]
    assert converted[1]["content"][0]["type"] == "thinking"  # blocks are sent back unchanged
    assert [r["tool_use_id"] for r in converted[2]["content"]] == ["tu1", "tu2"]


def test_claude_refusal_and_tools_conversion():
    assert "can't help" in ClaudeClient.from_claude({"content": [], "stop_reason": "refusal"})["content"]
    tools = ClaudeClient.to_claude_tools(
        [{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}]
    )
    assert tools == [{"name": "f", "description": "d", "input_schema": {"type": "object"}}]


def test_gemini_picks_flash_models():
    client = GeminiClient()
    available = [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "text-embedding-004",
        "gemini-2.5-flash-image",
    ]
    assert client._choose("instant", available) == "gemini-2.5-flash"
    assert (
        client._choose("powerful", ["gemini-9-flash-preview", "gemini-2.0-flash", "embedding-001"])
        == "gemini-9-flash-preview"
    )


@pytest.mark.asyncio
async def test_claude_request_shape(monkeypatch, settings):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Bonjour"}], "stop_reason": "end_turn"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real_client(*a, **{**k, "transport": httpx.MockTransport(handler)})
    )

    async def key(name):
        return "sk-ant-test"

    monkeypatch.setattr(llm_client, "aget_value", key)
    reply = await ClaudeClient().chat(
        settings.CLAUDE_POWERFUL_LLM,
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}],
    )
    assert reply["content"] == "Bonjour"
    request = sent[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant-test" and request.headers["anthropic-version"] == "2023-06-01"
    assert body["model"] == "claude-opus-5-5" and body["system"] == "sys" and body["tools"][0]["name"] == "f"
    assert body["fallbacks"] == "default" and request.headers["anthropic-beta"] == "server-side-fallback-2026-07-01"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_selected_provider_is_used(monkeypatch):
    from asgiref.sync import sync_to_async

    from app.services.app_settings import set_override

    await sync_to_async(set_override)("CHAT_PROVIDER", "gemini")
    assert isinstance(await llm_client.get_chat_client(), GeminiClient)
    await sync_to_async(set_override)("CHAT_PROVIDER", "")
    assert isinstance(await llm_client.get_chat_client(), llm_client.GroqClient)
