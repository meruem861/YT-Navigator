"""Tests for transcript selection and scan helpers (YouTube is faked)."""

from dataclasses import dataclass

import pytest

from app.services.scraping.transcript import TranscriptScraper


@dataclass
class FakeTranscript:
    """A transcript entry as listed by youtube-transcript-api."""

    language_code: str
    is_generated: bool
    text: str

    def fetch(self):
        transcript = self

        class Fetched:
            def to_raw_data(self):
                return [
                    {"text": transcript.text, "start": 0.0, "duration": 30.0},
                    {"text": "suite", "start": 30.0, "duration": 15.0},
                ]

        return Fetched()


def fake_api(transcripts):
    class FakeApi:
        def list(self, video_id):
            return iter(transcripts)

    return FakeApi


@pytest.mark.parametrize(
    "available, expected",
    [
        ([FakeTranscript("ar", True, "مرحبا")], "مرحبا"),  # auto-generated Arabic only
        ([FakeTranscript("ar", True, "auto"), FakeTranscript("fr", False, "manuel")], "manuel"),  # manual wins
    ],
)
def test_uses_best_transcript_in_any_language(monkeypatch, available, expected):
    monkeypatch.setattr("app.services.scraping.transcript.YouTubeTranscriptApi", fake_api(available))
    chunks = TranscriptScraper().get_video_transcript({"videoId": "abc"})
    assert chunks[0]["text"].startswith(expected)
    assert chunks[0]["video_id"] == "abc"


def test_no_transcript_returns_empty(monkeypatch):
    monkeypatch.setattr("app.services.scraping.transcript.YouTubeTranscriptApi", fake_api([]))
    assert TranscriptScraper().get_video_transcript({"videoId": "abc"}) == []


def test_blocked_requests_are_counted(monkeypatch):
    from youtube_transcript_api import RequestBlocked

    class BlockedApi:
        def list(self, video_id):
            raise RequestBlocked(video_id)

    monkeypatch.setattr("app.services.scraping.transcript.YouTubeTranscriptApi", BlockedApi)
    scraper = TranscriptScraper()
    assert scraper.get_video_transcript({"videoId": "abc"}) == []
    assert scraper.blocked_count == 1
