import logging

import feedparser
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    DigestItem,
    EpisodeResponse,
    PodcastCreate,
    PodcastResponse,
    SummaryResponse,
)
from app.db import crud
from app.db.database import get_session
from app.db.models import EpisodeStatus
from app.services.rss import poll_all_feeds, sync_feeds_from_yaml

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Podcasts ──────────────────────────────────────────────────


@router.get("/podcasts", response_model=list[PodcastResponse])
async def list_podcasts(session: AsyncSession = Depends(get_session)):
    return await crud.get_all_podcasts(session)


@router.post("/podcasts", response_model=PodcastResponse, status_code=201)
async def add_podcast(body: PodcastCreate, session: AsyncSession = Depends(get_session)):
    existing = await crud.get_podcast_by_rss_url(session, body.rss_url)
    if existing:
        raise HTTPException(status_code=409, detail="Podcast already subscribed")

    name = body.name
    if not name:
        feed = feedparser.parse(body.rss_url)
        name = feed.feed.get("title", body.rss_url)

    image_url = None
    if not body.name:
        image_url = feed.feed.get("image", {}).get("href")

    return await crud.create_podcast(session, name=name, rss_url=body.rss_url, image_url=image_url)


@router.delete("/podcasts/{podcast_id}", status_code=204)
async def remove_podcast(podcast_id: int, session: AsyncSession = Depends(get_session)):
    deleted = await crud.delete_podcast(session, podcast_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Podcast not found")


# ── Episodes ──────────────────────────────────────────────────


@router.get("/episodes", response_model=list[EpisodeResponse])
async def list_episodes(
    podcast_id: int | None = None,
    status: EpisodeStatus | None = None,
    session: AsyncSession = Depends(get_session),
):
    return await crud.get_episodes(session, podcast_id=podcast_id, status=status)


@router.get("/episodes/{episode_id}/summary", response_model=SummaryResponse)
async def get_episode_summary(episode_id: int, session: AsyncSession = Depends(get_session)):
    summary = await crud.get_summary_by_episode(session, episode_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary


# ── Digest ────────────────────────────────────────────────────


@router.get("/daily-digest", response_model=list[DigestItem])
async def daily_digest(session: AsyncSession = Depends(get_session)):
    items = await crud.get_daily_digest(session)
    return [
        DigestItem(
            episode=EpisodeResponse.model_validate(item["episode"]),
            podcast_name=item["podcast"].name,
            summary=SummaryResponse.model_validate(item["summary"]),
        )
        for item in items
    ]


# ── Manual trigger ────────────────────────────────────────────


@router.post("/process")
async def trigger_processing():
    await sync_feeds_from_yaml()
    results = await poll_all_feeds()
    return {"message": "Processing triggered", "new_episodes": results}
