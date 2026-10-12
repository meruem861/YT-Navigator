"""Tests for YouTube channel link parsing."""

import pytest

from app.services.scraping.utils import get_channel_username


@pytest.mark.parametrize(
    "link",
    [
        "https://www.youtube.com/@achachipodcast",
        "https://youtube.com/@achachipodcast",
        "https://youtube.com/@achachipodcast?si=AbC123xyz",
        "https://m.youtube.com/@achachipodcast/videos",
        "http://www.youtube.com/@achachipodcast/",
        "youtube.com/@achachipodcast",
        "  @achachipodcast  ",
        "HTTPS://WWW.YOUTUBE.COM/@achachipodcast",
    ],
)
def test_accepts_common_channel_link_forms(link):
    assert get_channel_username(link) == "achachipodcast"


def test_keeps_dots_dashes_and_underscores():
    assert get_channel_username("https://www.youtube.com/@Dr.Some_one-1") == "Dr.Some_one-1"


@pytest.mark.parametrize(
    "link",
    [
        "",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com/@achachipodcast",
        "https://www.youtube.com/channel/UC123",
        "achachipodcast",
    ],
)
def test_rejects_non_channel_links(link):
    with pytest.raises(ValueError, match="Invalid YouTube channel link format"):
        get_channel_username(link)
