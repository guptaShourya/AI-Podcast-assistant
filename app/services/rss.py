import logging
import ssl
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import certifi
import feedparser
import yaml

from app.config import settings
from app.db.crud import create_episodes_bulk, create_podcast, get_existing_guids, get_podcast_by_rss_url
from app.db.database import async_session

logger = logging.getLogger(__name__)

# Fix macOS SSL certificate issue for feedparser (urllib)
if hasattr(ssl, "_create_default_https_context"):
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())


def load_feeds_from_yaml() -> list[dict]:
    feeds_path = Path(settings.feeds_file)
    if not feeds_path.exists():
        logger.warning("Feeds file not found: %s", feeds_path)
        return []
    with open(feeds_path) as f:
        data = yaml.safe_load(f)
    return data.get("feeds", [])


def _parse_audio_url(entry: feedparser.FeedParserDict) -> str | None:
    for link in entry.get("links", []):
        if link.get("type", "").startswith("audio/"):
            return link.get("href")
    for enclosure in entry.get("enclosures", []):
        if enclosure.get("type", "").startswith("audio/"):
            return enclosure.get("href")
    return None


def _parse_duration(entry: feedparser.FeedParserDict) -> int | None:
    duration_str = entry.get("itunes_duration")
    if not duration_str:
        return None
    parts = str(duration_str).split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(parts[0])
    except (ValueError, IndexError):
        return None


def _parse_published(entry: feedparser.FeedParserDict) -> datetime | None:
    published = entry.get("published")
    if not published:
        return None
    try:
        return parsedate_to_datetime(published).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


async def poll_feed(rss_url: str, podcast_id: int) -> int:
    """Parse a single RSS feed and insert new episodes. Returns count of new episodes."""
    feed = feedparser.parse(rss_url)

    if feed.bozo and not feed.entries:
        logger.error("Failed to parse feed %s: %s", rss_url, feed.bozo_exception)
        return 0

    all_guids = [entry.get("id", entry.get("link", "")) for entry in feed.entries]
    all_guids = [g for g in all_guids if g]

    async with async_session() as session:
        existing = await get_existing_guids(session, all_guids)

        new_episodes = []
        for entry in feed.entries:
            guid = entry.get("id", entry.get("link", ""))
            if not guid or guid in existing:
                continue

            audio_url = _parse_audio_url(entry)
            if not audio_url:
                logger.debug("Skipping entry without audio: %s", entry.get("title", "unknown"))
                continue

            new_episodes.append(
                {
                    "podcast_id": podcast_id,
                    "guid": guid,
                    "title": entry.get("title", "Untitled"),
                    "description": entry.get("summary"),
                    "published_at": _parse_published(entry),
                    "audio_url": audio_url,
                    "duration_seconds": _parse_duration(entry),
                }
            )

        if new_episodes:
            await create_episodes_bulk(session, new_episodes)
            logger.info("Inserted %d new episodes from %s", len(new_episodes), rss_url)

    return len(new_episodes)


async def sync_feeds_from_yaml() -> None:
    """Load feeds from YAML and ensure they exist in the DB."""
    feeds = load_feeds_from_yaml()
    async with async_session() as session:
        for feed_info in feeds:
            rss_url = feed_info["rss_url"]
            existing = await get_podcast_by_rss_url(session, rss_url)
            if not existing:
                await create_podcast(session, name=feed_info["name"], rss_url=rss_url)
                logger.info("Added podcast from YAML: %s", feed_info["name"])


async def poll_all_feeds() -> dict[str, int]:
    """Poll all podcasts in the DB for new episodes. Returns {podcast_name: new_count}."""
    results = {}
    async with async_session() as session:
        from app.db.crud import get_all_podcasts

        podcasts = await get_all_podcasts(session)

    for podcast in podcasts:
        try:
            count = await poll_feed(podcast.rss_url, podcast.id)
            results[podcast.name] = count
        except Exception:
            logger.exception("Error polling feed: %s", podcast.name)
            results[podcast.name] = -1

    return results
