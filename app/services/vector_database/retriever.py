"""Vector retrieval functionality for the database.

This module provides semantic search over the embeddings stored in SQLite and keyword-based search
using the BM25 algorithm.
"""

from typing import List

import numpy as np
from asgiref.sync import sync_to_async
from rank_bm25 import BM25Okapi
from structlog import get_logger

from app.models import VideoChunk

from .utils import Document

logger = get_logger(__name__)


def chunk_to_document(chunk: VideoChunk, channel_id: str) -> Document:
    """Convert a VideoChunk row into a Document."""
    return Document(
        page_content=chunk.text,
        metadata={
            "id": chunk.id,
            "video_id": chunk.video_id,
            "start": chunk.start,
            "end": chunk.end,
            "text": chunk.text,
            "channel_id": channel_id,
        },
    )


class VectorRetriever:
    """Handles vector and keyword-based retrieval operations."""

    @staticmethod
    async def similarity_search(query_embedding: np.ndarray, channel_id: str, k: int = 20) -> List[Document]:
        """Find the chunks of a channel closest to the query embedding (cosine similarity).

        A channel holds at most a few thousand chunks, so a brute-force numpy search is fast enough
        and avoids needing a vector database extension.

        Args:
            query_embedding: Embedding of the search query.
            channel_id: The ID of the channel to search in.
            k: Number of results to return.

        Returns:
            List[Document]: The k most similar chunks, most similar first.
        """
        chunks = await sync_to_async(
            lambda: list(VideoChunk.objects.filter(video__channel_id=channel_id, embedding__isnull=False))
        )()
        if not chunks:
            return []

        matrix = np.vstack([np.frombuffer(chunk.embedding, dtype=np.float32) for chunk in chunks])
        if matrix.shape[1] != query_embedding.shape[0]:
            logger.error(
                "Embedding dimension mismatch, rescan the channel after changing EMBEDDING_MODEL",
                stored=matrix.shape[1],
                query=query_embedding.shape[0],
            )
            return []

        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_embedding)
        scores = matrix @ query_embedding / np.where(norms == 0, 1, norms)
        top = np.argsort(-scores)[:k]
        return [chunk_to_document(chunks[i], channel_id) for i in top]

    @classmethod
    async def keyword_search(cls, query: str, channel_id: str, k: int = 4) -> List[Document]:
        """Perform keyword-based search using BM25.

        Args:
            query: The search query string.
            channel_id: The ID of the channel to search in.
            k: Number of results to return.

        Returns:
            List[Document]: List of matching documents, empty list if the channel has no chunks.
        """
        chunks = await sync_to_async(
            lambda: list(VideoChunk.objects.filter(video__channel_id=channel_id).defer("embedding"))
        )()
        if not chunks:
            logger.warning("No Keyword retriever found for channel", channel_id=channel_id)
            return []

        documents = [chunk_to_document(chunk, channel_id) for chunk in chunks]
        bm25 = BM25Okapi([doc.page_content.split() for doc in documents])
        return bm25.get_top_n(query.split(), documents, n=k)
