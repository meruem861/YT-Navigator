"""Utility functions for YouTube scraping."""

import itertools
import re
from typing import (
    Any,
    List,
    Optional,
)

import scrapetube
import structlog

logger = structlog.get_logger(__name__)


# Accepts the forms YouTube and its app produce, e.g. https://www.youtube.com/@name, https://youtube.com/@name?si=...,
# https://m.youtube.com/@name/videos, youtube.com/@name and a bare @name
CHANNEL_LINK_PATTERN = re.compile(
    r"^\s*(?:(?:https?://)?(?:www\.|m\.)?youtube\.com/)?@(?P<username>[A-Za-z0-9._-]+)(?:[/?#].*)?\s*$",
    re.IGNORECASE,
)


def get_channel_username(channel_link: str) -> str:
    """Extract the username (handle without "@") from a YouTube channel link.

    Args:
        channel_link: The YouTube channel URL or handle

    Returns:
        str: The extracted channel username

    Raises:
        ValueError: If the link is not a YouTube channel link
    """
    match = CHANNEL_LINK_PATTERN.match(channel_link or "")
    if not match:
        raise ValueError("Invalid YouTube channel link format (expected e.g. https://www.youtube.com/@channel)")
    username = match.group("username")
    logger.debug("Extracted channel username", username=username)
    return username


def validate_channel_link(channel_link: str) -> str:
    """Validate the YouTube channel link format and existence.

    Args:
        channel_link: The YouTube channel link to validate

    Returns:
        str: The validated channel username

    Raises:
        ValueError: If the channel link is invalid or the channel doesn't exist
    """
    if not channel_link:
        error_msg = "Channel link cannot be empty"
        logger.error(error_msg)
        raise ValueError(error_msg)

    try:
        channel_username = get_channel_username(channel_link)
    except ValueError:
        logger.error("Invalid YouTube channel link format", channel_link=channel_link)
        raise

    try:
        scrapetube.get_channel(channel_username)
        logger.info("Channel validated successfully", channel_username=channel_username)
        return channel_username
    except Exception as e:
        logger.error("Channel validation failed", channel_username=channel_username, error=e)
        raise ValueError(f"Invalid YouTube channel: {str(e)}") from e


def chunk_generator(items: List[Any], chunk_size: int):
    """Generate chunks of items with a specified size.

    Args:
        items: List of items to chunk
        chunk_size: Size of each chunk

    Yields:
        List[Any]: Chunks of items
    """
    iterator = iter(items)
    chunk_count = 0

    while chunk := list(itertools.islice(iterator, chunk_size)):
        chunk_count += 1
        logger.debug(f"Processing chunk {chunk_count}", chunk_size=len(chunk))
        yield chunk
