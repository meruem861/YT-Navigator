"""Minimal async client for the Cohere embed and rerank APIs.

The official SDK is avoided on purpose: it pulls native dependencies that are hard to build on Android (Termux),
while the two endpoints used here are simple JSON calls.
"""

import asyncio
import time
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

MAX_RATE_LIMIT_RETRIES = 6
# Tokens sent in the last minute, shared by all clients: [(monotonic time, estimated tokens)]
_token_usage: List[Tuple[float, int]] = []


def _clock() -> float:
    return time.monotonic()


def estimate_tokens(texts: List[str]) -> int:
    """Conservative token estimate (non-Latin scripts such as Arabic use more tokens per character)."""
    return sum(len(text) for text in texts) // 2 + len(texts)


async def _wait_for_token_budget(tokens: int) -> None:
    """Pace requests to stay under the per-minute token limit of Cohere trial keys."""
    limit = settings.COHERE_TOKENS_PER_MINUTE
    while True:
        now = _clock()
        _token_usage[:] = [(t, n) for t, n in _token_usage if now - t < 60]
        used = sum(n for _, n in _token_usage)
        if not _token_usage or used + tokens <= limit:
            break
        wait = 60 - (now - _token_usage[0][0]) + 0.5
        logger.info("Pacing Cohere requests to respect the token rate limit", wait_seconds=round(wait, 1))
        await asyncio.sleep(wait)
    _token_usage.append((_clock(), tokens))


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

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
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
            if response.status_code != 429 or attempt == MAX_RATE_LIMIT_RETRIES:
                break
            # Rate limited (trial keys): wait for the per-minute window to reset, then retry
            try:
                wait = float(response.headers.get("Retry-After", 61))
            except ValueError:
                wait = 61
            logger.warning("Cohere rate limit reached, retrying", path=path, wait_seconds=wait, attempt=attempt + 1)
            await asyncio.sleep(wait)

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
        for batch in self._batches(texts):
            await _wait_for_token_budget(estimate_tokens(batch))
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
            logger.debug("Embedded batch", embedded=len(vectors), total=len(texts))

        return np.asarray(vectors, dtype=np.float32)

    @staticmethod
    def _batches(texts: List[str]) -> List[List[str]]:
        """Split texts into batches of at most EMBEDDING_BATCH_SIZE texts and a quarter of the token budget."""
        max_tokens = max(1, settings.COHERE_TOKENS_PER_MINUTE // 4)
        batches, batch = [], []
        for text in texts:
            if batch and (len(batch) >= settings.EMBEDDING_BATCH_SIZE or estimate_tokens(batch + [text]) > max_tokens):
                batches.append(batch)
                batch = []
            batch.append(text)
        if batch:
            batches.append(batch)
        return batches

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
