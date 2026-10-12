"""Tests for the settings page, API key overrides and single-user (Android app) mode."""

import pytest

from app.models import User
from app.services.app_settings import get_value


@pytest.fixture
def logged_in_client(client, db):
    user = User.objects.create_user(username="bob", password="pw")
    client.force_login(user)
    return client


def test_user_key_overrides_built_in_key(logged_in_client, settings):
    settings.GROQ_API_KEY = "built-in-groq"
    settings.COHERE_API_KEY = ""
    assert get_value("GROQ_API_KEY") == "built-in-groq"

    page = logged_in_client.get("/settings/").content.decode()
    assert "Using the built-in key" in page and "Not set" in page
    assert "built-in-groq" not in page

    logged_in_client.post("/settings/", {"GROQ_API_KEY": "  my-own-key-1234 ", "COHERE_API_KEY": ""})
    assert get_value("GROQ_API_KEY") == "my-own-key-1234"
    assert "ending in …1234" in logged_in_client.get("/settings/").content.decode()

    logged_in_client.post("/settings/", {"reset": "GROQ_API_KEY"})
    assert get_value("GROQ_API_KEY") == "built-in-groq"


def test_single_user_mode_skips_login(client, db, settings):
    settings.SINGLE_USER_MODE = True
    response = client.get("/chatbot/")
    assert response.status_code == 200
    assert User.objects.filter(username="me").count() == 1
    assert b'id="logout-form"' not in client.get("/").content

    client.get("/query/")
    assert User.objects.count() == 1


def test_login_required_without_single_user_mode(client, db, settings):
    settings.SINGLE_USER_MODE = False
    assert client.get("/chatbot/").status_code == 302


def test_chat_without_channel_returns_friendly_error(logged_in_client):
    response = logged_in_client.post("/send-message/", {"message": "hello"})
    assert response.status_code == 400
    assert "Connect a YouTube channel" in response.json()["response"]


def test_error_message_is_shown_once(logged_in_client):
    response = logged_in_client.post(
        "/get-channel-information/", {"channel_link": "https://example.com/x"}, follow=True
    )
    assert response.content.decode().count("Invalid YouTube channel link format") == 1


def test_test_keys_reports_each_service(logged_in_client, monkeypatch):
    from app.services.cohere_client import CohereError
    from app.services.groq_client import GroqError

    async def models(self):
        return ["openai/gpt-oss-20b", "whisper-large-v3"]

    async def bad_embed(self, texts, input_type):
        raise CohereError("invalid api token")

    monkeypatch.setattr("app.services.groq_client._models_cache", {})
    monkeypatch.setattr("app.services.groq_client.GroqClient.list_models", models)
    monkeypatch.setattr("app.services.cohere_client.CohereClient.embed", bad_embed)

    page = logged_in_client.post("/settings/test-keys/", follow=True).content.decode()
    assert "Groq key: works (chat models: openai/gpt-oss-20b, openai/gpt-oss-20b)" in page
    assert "Cohere key: not working (invalid api token)" in page

    async def groq_error(self):
        raise GroqError("Invalid API Key")

    monkeypatch.setattr("app.services.groq_client._models_cache", {})
    monkeypatch.setattr("app.services.groq_client.GroqClient.list_models", groq_error)
    page = logged_in_client.post("/settings/test-keys/", follow=True).content.decode()
    assert "Groq key: not working (Invalid API Key)" in page


def test_choose_model_prefers_candidates_then_any_chat_model():
    from app.services.groq_client import choose_model

    available = ["whisper-large-v3", "llama-3.3-70b-versatile", "openai/gpt-oss-120b"]
    assert choose_model(available, "", ["llama-3.1-8b-instant", "openai/gpt-oss-120b"]) == "openai/gpt-oss-120b"
    assert choose_model(available, "llama-3.3-70b-versatile", ["openai/gpt-oss-120b"]) == "llama-3.3-70b-versatile"
    assert choose_model(available, "", ["retired-model"]) == "llama-3.3-70b-versatile"
    assert choose_model(["whisper-large-v3"], "", []) is None
