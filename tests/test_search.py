"""Tests for chunk storage, semantic/keyword search and the SQL tool."""

import numpy as np
import pytest

from app.models import VideoChunk
from app.services.vector_database import (
    VectorDatabaseService,
    VectorRetriever,
)
from app.services.vector_database.tools import (
    SQLTools,
    VectorDatabaseTools,
)
from tests.conftest import SCRAPED_CHUNKS


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_add_chunks_stores_embeddings_and_skips_duplicates(fake_cohere, channel_with_videos):
    service = VectorDatabaseService()
    await service.add_chunks(SCRAPED_CHUNKS, channel_id="UC123")
    await service.add_chunks(SCRAPED_CHUNKS, channel_id="UC123")

    chunks = [c async for c in VideoChunk.objects.order_by("id")]
    assert len(chunks) == 4
    assert all(np.frombuffer(c.embedding, dtype=np.float32).shape == (64,) for c in chunks)
    assert str(chunks[3].start) == "01:01:40"
    # The second scan had nothing new, so only one embed call was made
    assert [path for path, _ in fake_cohere] == ["embed"]
    assert fake_cohere[0][1]["input_type"] == "search_document"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_similarity_and_keyword_search(fake_cohere, channel_with_videos):
    service = VectorDatabaseService()
    await service.add_chunks(SCRAPED_CHUNKS, channel_id="UC123")

    query_embedding = await service.embed_query("bread dough")
    results = await VectorRetriever.similarity_search(query_embedding, "UC123", k=2)
    assert [r.metadata["video_id"] for r in results] == ["vid2", "vid2"]
    assert results[0].page_content.startswith("knead")
    assert {"id", "video_id", "start", "end", "text", "channel_id"} <= results[0].metadata.keys()

    keyword_results = await VectorRetriever.keyword_search("salt", "UC123")
    assert keyword_results[0].metadata["video_id"] == "vid1"

    assert await VectorRetriever.similarity_search(query_embedding, "other-channel") == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_similarity_videos_search_end_to_end(fake_cohere, channel_with_videos):
    await VectorDatabaseService().add_chunks(SCRAPED_CHUNKS, channel_id="UC123")

    response = await VectorDatabaseTools.similarity_videos_search("bake bread", channel_id="UC123")

    assert response.videos[0].videoId == "vid2"
    assert response.videos[0].title == "Bread baking"
    assert all(0 <= c.score <= 100 for c in response.chunks)
    assert "rerank" in [path for path, _ in fake_cohere]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_search_falls_back_to_keywords_without_cohere(fake_cohere, channel_with_videos, monkeypatch):
    await VectorDatabaseService().add_chunks(SCRAPED_CHUNKS, channel_id="UC123")
    monkeypatch.setattr("django.conf.settings.COHERE_API_KEY", None)
    monkeypatch.setattr("app.services.cohere_client.CohereClient._post", _unconfigured_post)

    response = await VectorDatabaseTools.similarity_videos_search("salt", channel_id="UC123")

    assert response.videos[0].videoId == "vid1"


async def _unconfigured_post(self, path, payload):
    from app.services.cohere_client import CohereError

    raise CohereError("COHERE_API_KEY is not set")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_delete_video_removes_chunks(fake_cohere, channel_with_videos):
    service = VectorDatabaseService()
    await service.add_chunks(SCRAPED_CHUNKS, channel_id="UC123")

    assert await service.delete_video("vid1") > 0
    assert await VideoChunk.objects.filter(video_id="vid1").acount() == 0
    assert await VideoChunk.objects.filter(video_id="vid2").acount() == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_sql_tool_is_read_only(sql_db_file):
    rows = SQLTools.execute_query("SELECT id, title FROM app_video ORDER BY id")
    assert "'id': 'vid1'" in rows and "Bread baking" in rows

    assert SQLTools.execute_query("DELETE FROM app_video").startswith("Error")
    # Multiple statements are rejected by sqlite3, and the connection itself is read-only
    assert "#Error" in SQLTools.execute_query("SELECT 1 FROM app_video; DELETE FROM app_video")
    connection = SQLTools.get_db_connection()
    with pytest.raises(Exception, match="readonly"):
        connection.execute("DELETE FROM app_video")
    connection.close()


@pytest.mark.django_db
def test_sql_tool_schema_hides_embeddings():
    schema = str(SQLTools.get_tables_schema())
    assert "embedding" not in schema
    assert "SQLITE SYNTAX" in SQLTools.tool()["function"]["description"]
