"""Shared fixtures: fake Cohere and Groq so tests run offline."""

import hashlib
import os

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("DJANGO_SECRET_KEY", "test")

import numpy as np
import pytest
from django.utils import timezone

DIM = 64


def fake_embedding(text: str) -> np.ndarray:
    """Deterministic bag-of-words embedding: texts sharing words are similar."""
    vector = np.zeros(DIM, dtype=np.float32)
    for word in text.lower().split():
        vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1
    return vector


@pytest.fixture
def fake_cohere(monkeypatch):
    """Replace Cohere HTTP calls with local fakes and record them."""
    from app.services.cohere_client import CohereClient

    calls = []

    async def fake_post(self, path, payload):
        calls.append((path, payload))
        if path == "embed":
            return {"embeddings": {"float": [fake_embedding(t).tolist() for t in payload["texts"]]}}
        if path == "rerank":
            query_words = set(payload["query"].lower().split())
            scores = [
                len(query_words & set(d.lower().split())) / (len(query_words) or 1) for d in payload["documents"]
            ]
            order = sorted(range(len(scores)), key=lambda i: -scores[i])[: payload["top_n"]]
            return {"results": [{"index": i, "relevance_score": scores[i]} for i in order]}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(CohereClient, "_post", fake_post)
    monkeypatch.setattr("django.conf.settings.COHERE_API_KEY", "test")
    return calls


@pytest.fixture
def channel_with_videos(transactional_db):
    """A channel with two videos."""
    from app.models import (
        Channel,
        Video,
    )

    channel = Channel.objects.create(
        id="UC123", name="Cooking", profile_image_url="https://example.com/p.jpg", description="Food", username="cook"
    )
    for vid, title in [("vid1", "Pasta basics"), ("vid2", "Bread baking")]:
        Video.objects.create(
            id=vid,
            title=title,
            thumbnail="https://i.ytimg.com/vi/x/hq.jpg",
            published_at=timezone.now(),
            channel=channel,
        )
    return channel


SCRAPED_CHUNKS = [
    {"video_id": "vid1", "start_time": 0, "duration": 30, "text": "boil water and add salt for pasta"},
    {"video_id": "vid1", "start_time": 30, "duration": 40, "text": "cook the pasta until al dente"},
    {"video_id": "vid2", "start_time": 0, "duration": 35, "text": "knead the bread dough for ten minutes"},
    {"video_id": "vid2", "start_time": 3700, "duration": 20, "text": "bake the bread in a hot oven"},
]
