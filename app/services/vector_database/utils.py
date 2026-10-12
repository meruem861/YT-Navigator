"""Utility functions for vector database operations.

This module provides utility functions for calculating average scores and converting chunks
to minimal representations.
"""

from dataclasses import (
    dataclass,
    field,
)
from typing import List

from app.schemas import ChunkSchema


@dataclass
class Document:
    """A piece of text with metadata, as returned by the retrievers."""

    page_content: str
    metadata: dict = field(default_factory=dict)


def get_avg_score(chunks: List[ChunkSchema], video_id: str) -> float:
    """Calculate the average score for a video."""
    scores = [float(r.score) for r in chunks if r.videoId == video_id]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def minimise_chunks(chunks: List[dict]) -> List[ChunkSchema]:
    """Convert chunks to a minimal representation."""
    return [
        ChunkSchema(
            text=r["text"],
            start=str(r["start"]),
            end=str(r["end"]),
            videoId=r["video_id"],
            score=r["score"],
        )
        for r in chunks
        if all(key in r for key in ["text", "start", "end", "video_id", "score"])
    ]
