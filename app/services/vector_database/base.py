"""This module provides a service for managing vector database operations and embeddings.

The VectorDatabaseService class embeds transcript chunks with Cohere and stores them, together with
their embeddings, in the VideoChunk table.
"""

import traceback
from typing import List

import numpy as np
import structlog
from asgiref.sync import sync_to_async

from app.models import (
    Video,
    VideoChunk,
)
from app.services.cohere_client import CohereClient

logger = structlog.get_logger(__name__)


class VectorDatabaseService:
    """Service for managing vector database operations and embeddings."""

    def __init__(self):
        """Initialize the VectorDatabaseService with a Cohere client."""
        self.client = CohereClient()
        logger.info("VectorDatabaseService initialized")

    async def embed_query(self, query: str) -> np.ndarray:
        """Embed a search query.

        Args:
            query: The search query.

        Returns:
            np.ndarray: The query embedding.
        """
        return await self.client.embed_query(query)

    async def delete_video(self, video_id: str) -> int:
        """Delete a video and its chunks (embeddings are stored on the chunks).

        Args:
            video_id: The ID of the video to delete.

        Returns:
            int: Number of deleted records (0 if deletion fails).
        """
        try:
            return await sync_to_async(lambda: Video.objects.filter(id=video_id).delete()[0], thread_sensitive=True)()
        except Exception as e:
            logger.error(f"Error deleting video {video_id}", error=str(e), traceback=traceback.format_exc())
            return 0

    async def add_chunks(self, chunks: List[dict], channel_id: str) -> None:
        """Embed new transcript chunks and store them.

        Args:
            chunks: List of transcript chunks from the scraper.
            channel_id: Channel ID for the chunks.

        Raises:
            Exception: If there's an error embedding or storing chunks.
        """
        try:
            logger.info("Adding chunks to vector database", chunks_count=len(chunks))

            @sync_to_async(thread_sensitive=True)
            def get_existing_state():
                videos = {video.id: video for video in Video.objects.filter(channel_id=channel_id)}
                existing = set(VideoChunk.objects.filter(video__channel_id=channel_id).values_list("video_id", "text"))
                return videos, existing

            videos, existing = await get_existing_state()

            video_chunks = []
            for chunk in chunks:
                video_id = chunk.get("video_id")
                text = (chunk.get("text") or "").strip()
                if not text or video_id not in videos or (video_id, text) in existing:
                    continue
                existing.add((video_id, text))

                start_time = chunk.get("start_time")
                end_time = start_time + chunk.get("duration", 0) if start_time is not None else None
                video_chunks.append(
                    VideoChunk(
                        video=videos[video_id],
                        text=text,
                        start=self._format_time_for_django(start_time),
                        end=self._format_time_for_django(end_time),
                    )
                )

            if not video_chunks:
                logger.info("No new chunks to add")
                return

            logger.info("Embedding new chunks", new_chunks_count=len(video_chunks))
            embeddings = await self.client.embed([c.text for c in video_chunks], input_type="search_document")
            for video_chunk, embedding in zip(video_chunks, embeddings, strict=True):
                video_chunk.embedding = embedding.astype(np.float32).tobytes()

            logger.info("Creating VideoChunk objects", chunks_count=len(video_chunks))
            await sync_to_async(VideoChunk.objects.bulk_create, thread_sensitive=True)(video_chunks, batch_size=500)

        except Exception as e:
            logger.error("Error adding chunks", error=str(e), traceback=traceback.format_exc())
            raise

    def _format_time_for_django(self, seconds: float) -> str:
        """Format seconds into a time string compatible with Django TimeField.

        Args:
            seconds: Time in seconds.

        Returns:
            str: Time formatted as HH:MM:SS string.
        """
        if seconds is None:
            return None

        # Convert seconds to hours, minutes, seconds
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)

        # Format as HH:MM:SS
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
