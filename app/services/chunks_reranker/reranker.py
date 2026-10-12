"""Service for reranking document chunks using the Cohere rerank API."""

from typing import (
    Any,
    Dict,
    List,
)

from structlog import get_logger

from app.services.cohere_client import CohereClient
from app.services.vector_database.utils import Document

logger = get_logger(__name__)


class ChunksReRanker:
    """Reranks document chunks with a hosted cross-encoder (Cohere rerank)."""

    _client = CohereClient()

    @classmethod
    async def rerank(cls, query: str, docs: List[Document]) -> List[Dict[str, Any]]:
        """Rerank documents by relevance to the query.

        Args:
            query: The search query
            docs: List of documents to rerank

        Returns:
            List of ranked documents with scores, highest score first
        """
        if not docs:
            logger.warning("No documents provided for reranking")
            return []

        logger.info("Starting reranking", num_docs=len(docs))
        ranking = await cls._client.rerank(query, [doc.page_content for doc in docs])

        ranked_docs = [
            {"score": score, **docs[idx].metadata, "text": docs[idx].page_content} for idx, score in ranking
        ]
        ranked_docs.sort(key=lambda x: x["score"], reverse=True)

        logger.info("Completed reranking", num_docs=len(docs))
        return ranked_docs
