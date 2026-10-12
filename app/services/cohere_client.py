"""Minimal async client for the Cohere embed and rerank APIs.

The official SDK is avoided on purpose: it pulls native dependencies that are hard to build on Android (Termux),
while the two endpoints used here are simple JSON calls.
"""

from typing import (
    List,
    Literal,
    Tuple,
)

import httpx
import numpy as np
import structlog
from django.conf import settings

from app.services.app_settings import aget_value

logger = structlog.get_logger(__name__)

InputType = Literal["search_document", "search_query"]


class CohereError(RuntimeError):
    """Raised when the Cohere API returns an error or is not configured."""


class CohereClient:
    """Async client for Cohere embeddings and reranking."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 60.0):
        """Initialize the client.

        Args:
            api_key: Cohere API key, defaults to the key saved in Settings or the built-in one.
            base_url: Cohere API base URL, defaults to settings.COHERE_API_URL.
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key
        self.base_url = (base_url or settings.COHERE_API_URL).rstrip("/")
        self.timeout = timeout

    async def _post(self, path: str, payload: dict) -> dict:
        """Send a POST request to the Cohere API and return the JSON response."""
        api_key = self.api_key or await aget_value("COHERE_API_KEY")
        if not api_key:
            raise CohereError("No Cohere API key set. Add one in Settings.")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/{path}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

        if response.status_code != 200:
            logger.error("Cohere API error", path=path, status_code=response.status_code, body=response.text[:500])
            raise CohereError(f"Cohere {path} failed with status {response.status_code}: {response.text[:200]}")
        return response.json()

    async def embed(self, texts: List[str], input_type: InputType) -> np.ndarray:
        """Embed texts in batches.

        Args:
            texts: Texts to embed.
            input_type: "search_document" for stored chunks, "search_query" for user queries.

        Returns:
            np.ndarray: float32 matrix of shape (len(texts), dimension).
        """
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        vectors = []
        batch_size = settings.EMBEDDING_BATCH_SIZE
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            data = await self._post(
                "embed",
                {
                    "model": settings.EMBEDDING_MODEL,
                    "texts": batch,
                    "input_type": input_type,
                    "embedding_types": ["float"],
                },
            )
            vectors.extend(data["embeddings"]["float"])
            logger.debug("Embedded batch", batch_start=i, batch_size=len(batch))

        return np.asarray(vectors, dtype=np.float32)

    async def embed_query(self, query: str) -> np.ndarray:
        """Embed a single search query."""
        return (await self.embed([query], input_type="search_query"))[0]

    async def rerank(self, query: str, documents: List[str], top_n: int | None = None) -> List[Tuple[int, float]]:
        """Rerank documents by relevance to the query.

        Args:
            query: The search query.
            documents: Documents to rerank.
            top_n: Number of results to return, defaults to all documents.

        Returns:
            List of (document index, relevance score), most relevant first.
        """
        if not documents:
            return []

        data = await self._post(
            "rerank",
            {
                "model": settings.RERANKER_MODEL_NAME,
                "query": query,
                "documents": documents,
                "top_n": top_n or len(documents),
            },
        )
        return [(r["index"], float(r["relevance_score"])) for r in data["results"]]
