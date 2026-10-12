"""Tests for listing channel videos (YouTube responses are faked)."""

import json

import pytest

from app.services.scraping import video_list
from app.services.scraping.video_list import (
    extract_videos,
    list_channel_videos,
    list_from_channel_page,
    parse_rss,
)


def lockup(video_id, title, published="2 days ago"):
    return {
        "richItemRenderer": {
            "content": {
                "lockupViewModel": {
                    "contentId": video_id,
                    "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                    "contentImage": {
                        "thumbnailViewModel": {
                            "image": {"sources": [{"url": f"https://i.ytimg.com/vi/{video_id}/x.jpg"}]}
                        }
                    },
                    "metadata": {
                        "lockupMetadataViewModel": {
                            "title": {"content": title},
                            "metadata": {
                                "contentMetadataViewModel": {
                                    "metadataRows": [
                                        {
                                            "metadataParts": [
                                                {"text": {"content": "1.2K views"}},
                                                {"text": {"content": published}},
                                            ]
                                        }
                                    ]
                                }
                            },
                        }
                    },
                }
            }
        }
    }


def renderer(video_id, title):
    return {
        "richItemRenderer": {
            "content": {
                "videoRenderer": {
                    "videoId": video_id,
                    "title": {"runs": [{"text": title}]},
                    "publishedTimeText": {"simpleText": "Streamed 3 weeks ago"},
                    "thumbnail": {"thumbnails": [{"url": "small.jpg"}, {"url": "big.jpg"}]},
                }
            }
        }
    }


def continuation(token):
    return {"continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": token}}}}


def page(items):
    data = {
        "contents": {
            "twoColumnBrowseResultsRenderer": {
                "tabs": [{"tabRenderer": {"content": {"richGridRenderer": {"contents": items}}}}]
            }
        }
    }
    return (
        "<html><script>var ytInitialData = " + json.dumps(data) + ";</script>"
        '<script>ytcfg.set({"INNERTUBE_API_KEY":"KEY","INNERTUBE_CLIENT_VERSION":"2.2026"});</script></html>'
    )


class FakeResponse:
    def __init__(self, text="", data=None):
        self.text = text
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, html, pages):
        self.html = html
        self.pages = list(pages)
        self.posts = []

    def get(self, url, params=None, timeout=None):
        assert url == "https://www.youtube.com/@chan/videos"
        return FakeResponse(text=self.html)

    def post(self, url, params=None, json=None, timeout=None):
        self.posts.append(json["continuation"])
        return FakeResponse(data=self.pages.pop(0))


def test_extracts_new_and_classic_formats_in_order():
    videos = extract_videos({"a": [lockup("v1", "عنوان"), renderer("v2", "Classic")]})
    assert [v["videoId"] for v in videos] == ["v1", "v2"]
    assert videos[0]["title"]["runs"][0]["text"] == "عنوان"
    assert videos[0]["publishedTimeText"]["simpleText"] == "2 days ago"
    assert videos[0]["thumbnail"]["thumbnails"][-1]["url"] == "https://i.ytimg.com/vi/v1/x.jpg"
    assert videos[1]["thumbnail"]["thumbnails"][-1]["url"] == "big.jpg"
    assert videos[1]["publishedTimeText"]["simpleText"] == "Streamed 3 weeks ago"


def test_follows_continuations_until_limit():
    html = page([lockup("v1", "One"), lockup("v2", "Two"), continuation("T1")])
    more = {
        "onResponseReceivedActions": [
            {
                "appendContinuationItemsAction": {
                    "continuationItems": [lockup("v3", "Three"), lockup("v4", "Four"), continuation("T2")]
                }
            }
        ]
    }
    session = FakeSession(html, [more])

    videos = list_from_channel_page("chan", limit=3, session=session)

    assert [v["videoId"] for v in videos] == ["v1", "v2", "v3"]
    assert session.posts == ["T1"]


def test_stops_when_no_more_pages():
    session = FakeSession(page([lockup("v1", "One")]), [])
    assert [v["videoId"] for v in list_from_channel_page("chan", limit=50, session=session)] == ["v1"]


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <yt:videoId>abc</yt:videoId>
  <title>حلقة جديدة</title>
  <published>2026-10-01T10:00:00+00:00</published>
  <media:group><media:thumbnail url="https://i.ytimg.com/vi/abc/hqdefault.jpg" width="480" height="360"/></media:group>
 </entry>
</feed>"""


def test_parse_rss():
    [video] = parse_rss(RSS)
    assert video["videoId"] == "abc"
    assert video["title"]["runs"][0]["text"] == "حلقة جديدة"
    assert video["published_at"].year == 2026


def test_falls_back_to_rss_then_reports_errors(monkeypatch):
    def broken_page(*args, **kwargs):
        raise ValueError("ytInitialData not found")

    monkeypatch.setattr(video_list, "list_from_channel_page", broken_page)
    monkeypatch.setattr(video_list, "list_from_rss", lambda channel_id, limit: parse_rss(RSS)[:limit])
    assert [v["videoId"] for v in list_channel_videos("chan", "UC123", 10)] == ["abc"]

    monkeypatch.setattr(video_list, "list_from_rss", lambda channel_id, limit: [])
    with pytest.raises(RuntimeError, match="ytInitialData not found.*RSS feed: no videos"):
        list_channel_videos("chan", "UC123", 10)


@pytest.mark.django_db
def test_formatted_metadata_uses_exact_rss_date():
    from app.services.scraping.video import VideoScraper

    metadata = VideoScraper().get_formatted_video_metadata(parse_rss(RSS)[0])
    assert metadata["published_at"].isoformat().startswith("2026-10-01")
