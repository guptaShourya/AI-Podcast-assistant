import logging

import feedparser
from fastmcp import FastMCP

from app.db import crud
from app.db.database import async_session

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Podcast Assistant",
    instructions=(
        "You help users stay on top of their podcast subscriptions. "
        "You can show today's digest, search episodes, get summaries, "
        "add new podcasts, and list subscriptions."
    ),
)


@mcp.tool()
async def get_daily_digest() -> str:
    """Get today's episode summaries ranked by listen-worthiness score (1-10)."""
    async with async_session() as session:
        items = await crud.get_daily_digest(session)

    if not items:
        return "No new episode summaries in the last 24 hours."

    lines = []
    for item in items:
        ep = item["episode"]
        s = item["summary"]
        p = item["podcast"]
        lines.append(
            f"**[{s.listen_score}/10] {ep.title}** ({p.name})\n"
            f"  Summary: {s.summary_text}\n"
            f"  Topics: {', '.join(s.key_topics)}\n"
            f"  Highlights:\n" + "\n".join(f"    - {h}" for h in s.highlights)
        )

    return f"Daily Digest ({len(items)} episodes):\n\n" + "\n\n---\n\n".join(lines)


@mcp.tool()
async def search_episodes(query: str) -> str:
    """Search across episode summaries by keyword. Returns matching episodes with summaries."""
    async with async_session() as session:
        items = await crud.search_episodes(session, query)

    if not items:
        return f"No episodes found matching '{query}'."

    lines = []
    for item in items:
        ep = item["episode"]
        s = item["summary"]
        p = item["podcast"]
        lines.append(
            f"**[{s.listen_score}/10] {ep.title}** ({p.name})\n"
            f"  Summary: {s.summary_text}\n"
            f"  Topics: {', '.join(s.key_topics)}"
        )

    return f"Found {len(items)} episode(s) for '{query}':\n\n" + "\n\n---\n\n".join(lines)


@mcp.tool()
async def get_podcast_summary(episode_id: int) -> str:
    """Get the full summary, topics, highlights, and transcript for a specific episode."""
    async with async_session() as session:
        summary = await crud.get_summary_by_episode(session, episode_id)

    if not summary:
        return f"No summary found for episode {episode_id}."

    return (
        f"**Listen Score: {summary.listen_score}/10**\n\n"
        f"**Summary:** {summary.summary_text}\n\n"
        f"**Key Topics:** {', '.join(summary.key_topics)}\n\n"
        f"**Highlights:**\n" + "\n".join(f"- {h}" for h in summary.highlights) + "\n\n"
        f"**Transcript ({len(summary.transcript_text)} chars):**\n{summary.transcript_text[:2000]}..."
    )


@mcp.tool()
async def add_podcast(rss_url: str) -> str:
    """Subscribe to a new podcast by its RSS feed URL."""
    async with async_session() as session:
        existing = await crud.get_podcast_by_rss_url(session, rss_url)
        if existing:
            return f"Already subscribed to '{existing.name}'."

        feed = feedparser.parse(rss_url)
        name = feed.feed.get("title", rss_url)
        image_url = feed.feed.get("image", {}).get("href")

        podcast = await crud.create_podcast(session, name=name, rss_url=rss_url, image_url=image_url)

    return f"Subscribed to '{podcast.name}'. New episodes will be picked up on the next poll cycle."


@mcp.tool()
async def list_podcasts() -> str:
    """List all podcast subscriptions."""
    async with async_session() as session:
        podcasts = await crud.get_all_podcasts(session)

    if not podcasts:
        return "No podcast subscriptions yet. Use add_podcast to subscribe."

    lines = [f"- **{p.name}** (id={p.id}): {p.rss_url}" for p in podcasts]
    return f"Subscriptions ({len(podcasts)}):\n" + "\n".join(lines)
