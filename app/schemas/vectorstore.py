"""Data models for search results.

This module defines data models used for representing video chunks,
video metadata, and vector store query responses.
"""

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from typing import Optional


@dataclass
class ChunkSchema:
    """Represents a transcript chunk from a video.

    Attributes:
        text: The textual content of the transcript chunk.
        start: Start time of the chunk in string format.
        end: End time of the chunk in string format.
        videoId: Unique identifier of the source video.
        score: Relevance or similarity score of the chunk.
        start_in_seconds: Optional start time in floating-point seconds.
    """

    text: str
    start: str
    end: str
    videoId: str
    score: float
    start_in_seconds: Optional[float] = None


@dataclass
class VideoSchema:
    """Represents metadata for a YouTube video.

    Attributes:
        videoId: Unique identifier of the video.
        title: Title of the video.
        thumbnail: URL or path to the video's thumbnail image.
        published_at: Timestamp of when the video was published.
        avg_score: Optional average relevance score for the video.
    """

    videoId: str
    title: str
    thumbnail: str
    published_at: str
    avg_score: Optional[float] = None


@dataclass
class QueryVectorStoreResponse:
    """Represents the response from a search: matching transcript chunks and their videos."""

    chunks: list[ChunkSchema] = field(default_factory=list)
    videos: list[VideoSchema] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert the response to plain dicts (e.g. to send it to the LLM as JSON)."""
        return asdict(self)
