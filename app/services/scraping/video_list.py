"""List the videos of a YouTube channel.

YouTube regularly changes the structure of its pages (e.g. classic ``videoRenderer`` items were replaced by
``lockupViewModel`` items), which silently broke scrapetube. This module reads both formats generically from the
channel's "Videos" tab (following continuation pages), and falls back to the channel's RSS feed (latest ~15 videos),
which is a small, stable XML document.

Each video is returned in the scrapetube-like shape expected by ``VideoScraper.get_formatted_video_metadata``.
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Optional,
)

import requests
import structlog

logger = structlog.get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_PAGES = 20


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    # Skip the cookie consent interstitial
    session.cookies.set("CONSENT", "YES+cb", domain=".youtube.com")
    session.cookies.set("SOCS", "CAI", domain=".youtube.com")
    return session


def _walk(node: Any) -> Iterator[Dict]:
    """Yield every dict in a JSON tree, depth-first in document order."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def _text(value: Any) -> str:
    """Read YouTube's text objects: {"simpleText": ...}, {"runs": [...]} or {"content": ...}."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "simpleText" in value:
            return value["simpleText"]
        if "runs" in value:
            return "".join(run.get("text", "") for run in value["runs"])
        if "content" in value:
            return value["content"]
    return ""


def _video(video_id: str, title: str, published: str = "", thumbnail: str = "", **extra) -> Dict:
    return {
        "videoId": video_id,
        "title": {"runs": [{"text": title or "Untitled Video"}]},
        "publishedTimeText": {"simpleText": published},
        "thumbnail": {"thumbnails": [{"url": thumbnail or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}]},
        **extra,
    }


def _from_renderer(renderer: Dict) -> Optional[Dict]:
    """Classic videoRenderer / gridVideoRenderer / playlistVideoRenderer item."""
    video_id = renderer.get("videoId")
    if not video_id:
        return None
    thumbnails = renderer.get("thumbnail", {}).get("thumbnails") or [{}]
    return _video(
        video_id,
        _text(renderer.get("title")),
        _text(renderer.get("publishedTimeText")),
        thumbnails[-1].get("url", ""),
        lengthText={"simpleText": _text(renderer.get("lengthText"))},
    )


def _from_lockup(lockup: Dict) -> Optional[Dict]:
    """New lockupViewModel item (contentId + nested view models)."""
    video_id = lockup.get("contentId")
    if not video_id or "VIDEO" not in str(lockup.get("contentType", "VIDEO")):
        return None
    metadata = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = _text(metadata.get("title"))
    texts = [_text(d.get("text")) for d in _walk(metadata.get("metadata", {})) if "text" in d]
    published = next((t for t in texts if re.search(r"\bago\b", t)), "")
    sources = next((d["sources"] for d in _walk(lockup.get("contentImage", {})) if d.get("sources")), [{}])
    return _video(video_id, title, published, sources[-1].get("url", ""))


def extract_videos(data: Any) -> List[Dict]:
    """Extract videos (both page formats) from a ytInitialData / browse response, in page order."""
    videos = []
    for node in _walk(data):
        for key in ("videoRenderer", "gridVideoRenderer", "playlistVideoRenderer"):
            if isinstance(node.get(key), dict):
                video = _from_renderer(node[key])
                if video:
                    videos.append(video)
        if isinstance(node.get("lockupViewModel"), dict):
            video = _from_lockup(node["lockupViewModel"])
            if video:
                videos.append(video)
    return videos


def _continuation_token(data: Any) -> Optional[str]:
    tokens = [
        node["continuationCommand"]["token"]
        for node in _walk(data)
        if isinstance(node.get("continuationCommand"), dict) and node["continuationCommand"].get("token")
    ]
    # The grid's "load more" token comes after the items
    return tokens[-1] if tokens else None


def _initial_data(html: str) -> Dict:
    start = html.find("ytInitialData = ")
    if start < 0:
        start = html.find('ytInitialData"] = ')
        if start < 0:
            raise ValueError("ytInitialData not found in the channel page")
    start = html.index("{", start)
    return json.JSONDecoder().raw_decode(html[start:])[0]


def _config(html: str, key: str) -> Optional[str]:
    match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html)
    return match.group(1) if match else None


def list_from_channel_page(
    channel_username: str, limit: int, session: Optional[requests.Session] = None
) -> List[Dict]:
    """List videos from the channel's "Videos" tab, following continuation pages until ``limit``."""
    session = session or _session()
    response = session.get(f"https://www.youtube.com/@{channel_username}/videos", params={"hl": "en"}, timeout=20)
    response.raise_for_status()
    html = response.text
    data = _initial_data(html)

    videos: Dict[str, Dict] = {}
    for video in extract_videos(data):
        videos.setdefault(video["videoId"], video)

    api_key = _config(html, "INNERTUBE_API_KEY")
    client_version = _config(html, "INNERTUBE_CLIENT_VERSION") or "2.20250101.00.00"
    token = _continuation_token(data)
    pages = 0
    while len(videos) < limit and token and api_key and pages < MAX_PAGES:
        pages += 1
        response = session.post(
            "https://www.youtube.com/youtubei/v1/browse",
            params={"key": api_key, "prettyPrint": "false"},
            json={
                "context": {"client": {"clientName": "WEB", "clientVersion": client_version, "hl": "en"}},
                "continuation": token,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        before = len(videos)
        for video in extract_videos(data):
            videos.setdefault(video["videoId"], video)
        next_token = _continuation_token(data)
        if len(videos) == before or next_token == token:
            break
        token = next_token

    return list(videos.values())[:limit]


ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA = "{http://search.yahoo.com/mrss/}"


def parse_rss(xml_text: str) -> List[Dict]:
    """Parse a channel RSS feed into videos."""
    videos = []
    for entry in ET.fromstring(xml_text).iter(f"{ATOM}entry"):
        video_id = entry.findtext(f"{YT}videoId")
        if not video_id:
            continue
        thumbnail = entry.find(f".//{MEDIA}thumbnail")
        published = entry.findtext(f"{ATOM}published")
        extra = {}
        if published:
            try:
                extra["published_at"] = datetime.fromisoformat(published)
            except ValueError:
                pass
        videos.append(
            _video(
                video_id,
                entry.findtext(f"{ATOM}title") or "",
                thumbnail=thumbnail.get("url", "") if thumbnail is not None else "",
                **extra,
            )
        )
    return videos


def list_from_rss(channel_id: str, limit: int, session: Optional[requests.Session] = None) -> List[Dict]:
    """List the latest videos (about 15) from the channel's RSS feed."""
    session = session or _session()
    response = session.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}, timeout=20)
    response.raise_for_status()
    return parse_rss(response.text)[:limit]


def list_channel_videos(channel_username: str, channel_id: Optional[str], limit: int) -> List[Dict]:
    """List up to ``limit`` videos of a channel, newest first.

    Raises:
        RuntimeError: If no method could list any video (with the reasons).
    """
    errors = []
    try:
        videos = list_from_channel_page(channel_username, limit)
        if videos:
            logger.info("Listed videos from the channel page", count=len(videos))
            return videos
        errors.append("channel page: no videos found")
    except Exception as e:
        logger.warning("Listing videos from the channel page failed", error=str(e))
        errors.append(f"channel page: {type(e).__name__}: {e}")

    if channel_id and channel_id.startswith("UC"):
        try:
            videos = list_from_rss(channel_id, limit)
            if videos:
                logger.info("Listed videos from the RSS feed", count=len(videos))
                return videos
            errors.append("RSS feed: no videos")
        except Exception as e:
            logger.warning("Listing videos from the RSS feed failed", error=str(e))
            errors.append(f"RSS feed: {type(e).__name__}: {e}")

    raise RuntimeError("; ".join(errors))
