"""Tests for the Groq and Cohere HTTP clients (HTTP is faked with httpx.MockTransport)."""

import json

import httpx
import pytest

from app.services import cohere_client
from app.services import llm_client as groq_client


@pytest.fixture
def mock_http(monkeypatch):
    """Route httpx.AsyncClient requests to a handler; returns the list of requests made."""
    calls = []
    state = {}

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: (calls.append(request), state["handler"](request))[1]
        )
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(cohere_client.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(groq_client.asyncio, "sleep", fake_sleep)

    async def key(name):
        return "test-key"

    monkeypatch.setattr(cohere_client, "aget_value", key)
    monkeypatch.setattr(groq_client, "aget_value", key)
    return calls, sleeps, state


@pytest.mark.asyncio
async def test_cohere_retries_after_rate_limit(mock_http):
    calls, sleeps, state = mock_http
    responses = iter([httpx.Response(429, json={"message": "trial token rate limit exceeded"})])

    def handler(request):
        body = json.loads(request.content)
        return next(responses, None) or httpx.Response(
            200, json={"embeddings": {"float": [[1.0, 0.0]] * len(body["texts"])}}
        )

    state["handler"] = handler
    vectors = await cohere_client.CohereClient().embed(["a", "b"], input_type="search_document")
    assert vectors.shape == (2, 2)
    assert len(calls) == 2 and sleeps == [61]


@pytest.mark.asyncio
async def test_cohere_paces_batches_under_token_budget(mock_http, settings, monkeypatch):
    calls, sleeps, state = mock_http
    settings.COHERE_TOKENS_PER_MINUTE = 1000
    monkeypatch.setattr(cohere_client, "_token_usage", [])
    clock = {"now": 1000.0}
    monkeypatch.setattr(cohere_client, "_clock", lambda: clock["now"])

    async def advancing_sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(cohere_client.asyncio, "sleep", advancing_sleep)

    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"embeddings": {"float": [[0.5]] * len(body["texts"])}})

    state["handler"] = handler
    texts = ["x" * 400] * 6  # ~201 tokens each, so 1 text per batch (budget/4 = 250) and ~4 per minute
    vectors = await cohere_client.CohereClient().embed(texts, input_type="search_document")
    assert vectors.shape == (6, 1)
    assert len(calls) == 6
    assert sleeps, "should wait for the per-minute window before exceeding the budget"


@pytest.mark.asyncio
async def test_groq_retries_spontaneous_tool_call(mock_http):
    calls, sleeps, state = mock_http
    responses = iter(
        [httpx.Response(400, json={"error": {"message": "Tool choice is none, but model called a tool"}})]
    )

    def handler(request):
        return next(responses, None) or httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        )

    state["handler"] = handler
    reply = await groq_client.GroqClient().chat("m", [{"role": "user", "content": "hi"}], json_mode=True)
    assert reply["content"] == "ok"
    retried = json.loads(calls[1].content)
    assert retried["messages"][-1]["content"] == groq_client.NO_TOOLS_REMINDER


@pytest.mark.asyncio
async def test_groq_waits_on_short_rate_limit_and_reports_long_ones(mock_http):
    calls, sleeps, state = mock_http
    state["handler"] = lambda request: httpx.Response(
        429, json={"error": {"message": "Rate limit reached. Please try again in 2.5s."}}
    )
    with pytest.raises(groq_client.GroqError, match="Rate limit"):
        await groq_client.GroqClient().chat("m", [{"role": "user", "content": "hi"}])
    assert sleeps == [3.0, 3.0] and len(calls) == 3

    calls.clear(), sleeps.clear()
    state["handler"] = lambda request: httpx.Response(
        429, json={"error": {"message": "Rate limit reached. Please try again in 5m10.2s."}}
    )
    with pytest.raises(groq_client.GroqError):
        await groq_client.GroqClient().chat("m", [{"role": "user", "content": "hi"}])
    assert sleeps == [] and len(calls) == 1
