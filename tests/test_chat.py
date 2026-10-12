"""Tests for the chat agent with SQLite-backed history (LLMs are faked)."""

import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.models import User
from app.services.agent.main_graph import AgentGraph
from app.services.vector_database import VectorDatabaseService
from tests.conftest import SCRAPED_CHUNKS


def fake_model(*replies):
    return GenericFakeChatModel(messages=iter(replies))


@pytest.fixture
def chat_setup(tmp_path, settings, channel_with_videos):
    settings.CHECKPOINT_DB_PATH = tmp_path / "checkpoints.sqlite3"
    user = User.objects.create_user(username="alice", password="pw", channel=channel_with_videos)
    return AgentGraph(), user, channel_with_videos


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_chat_without_tools_persists_history(chat_setup):
    agent, user, channel = chat_setup
    agent.model = fake_model(
        AIMessage(content=json.dumps({"answer": "No"})),
        AIMessage(content=json.dumps({"placeholder": "Hello **there**", "videos": []})),
    )

    response = await agent.process_message("hi", channel=channel, user=user)
    assert "<strong>there</strong>" in json.loads(response)["placeholder"]

    history = await agent.get_chat_history(str(user.id))
    assert [m.type for m in history] == ["human", "ai"]
    assert "hi" in history[0].placeholder

    await agent.clear_chat_history(str(user.id))
    assert await agent.get_chat_history(str(user.id)) == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_chat_with_search_tool(chat_setup, fake_cohere, monkeypatch):
    agent, user, channel = chat_setup
    await VectorDatabaseService().add_chunks(SCRAPED_CHUNKS, channel_id=channel.id)

    agent.model = fake_model(AIMessage(content=json.dumps({"answer": "Yes"})))
    final = {
        "placeholder": "Watch the bread video",
        "videos": [
            {"title": "Bread baking", "id": "vid2", "timestamps": [], "description": "bread", "thumbnail_url": None}
        ],
    }
    react_model = fake_model(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "similarity_videos_search",
                    "args": {"query": "bread", "channel_id": channel.id},
                    "id": "call1",
                }
            ],
        ),
        AIMessage(content=json.dumps(final)),
    )
    monkeypatch.setattr("app.services.agent.react_graph.model", react_model)

    response = await agent.process_message("how do I bake bread?", channel=channel, user=user)
    assert json.loads(response)["videos"][0]["id"] == "vid2"

    history = await agent.get_chat_history(str(user.id))
    assert history[-1].videos[0].id == "vid2"
