from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import feedparser

from app.db.crud import (
    create_podcast,
    delete_podcast,
    get_all_podcasts,
    get_daily_digest,
    get_podcast_by_rss_url,
    get_summary_by_episode,
)
from app.db.database import async_session
from app.db.models import Episode
from app.services.pipeline import process_pending_episodes
from app.services.rss import poll_feed

from sqlalchemy import select
from sqlalchemy.orm import selectinload

templates = Jinja2Templates(directory="app/ui/templates")

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("", response_class=HTMLResponse)
async def digest_page(request: Request):
    async with async_session() as session:
        digest = await get_daily_digest(session)
    items = []
    for d in digest:
        items.append(
            {
                "episode": d["episode"],
                "summary": d["summary"],
                "podcast_name": d["podcast"].name if d["podcast"] else "Unknown",
            }
        )
    return templates.TemplateResponse(
        request, "digest.html", {"digest": items, "active": "digest"}
    )


@router.get("/podcasts", response_class=HTMLResponse)
async def podcasts_page(request: Request):
    async with async_session() as session:
        podcasts = await get_all_podcasts(session)
    return templates.TemplateResponse(
        request, "podcasts.html",
        {"podcasts": podcasts, "active": "podcasts"},
    )


@router.post("/podcasts/add")
async def add_podcast(rss_url: str = Form(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    async with async_session() as session:
        existing = await get_podcast_by_rss_url(session, rss_url)
        if not existing:
            feed = feedparser.parse(rss_url)
            name = feed.feed.get("title", rss_url)
            image_url = feed.feed.get("image", {}).get("href")
            podcast = await create_podcast(session, name=name, rss_url=rss_url, image_url=image_url)
            # Immediately poll the new feed for recent episodes
            await poll_feed(rss_url, podcast.id)
            # Process (transcribe + summarize) in the background
            background_tasks.add_task(process_pending_episodes)
    return RedirectResponse(url="/ui/podcasts", status_code=303)


@router.post("/podcasts/{podcast_id}/delete")
async def remove_podcast(podcast_id: int):
    async with async_session() as session:
        await delete_podcast(session, podcast_id)
    return RedirectResponse(url="/ui/podcasts", status_code=303)


@router.get("/episode/{episode_id}", response_class=HTMLResponse)
async def episode_page(request: Request, episode_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Episode)
            .options(selectinload(Episode.podcast))
            .where(Episode.id == episode_id)
        )
        episode = result.scalar_one_or_none()
        if not episode:
            return HTMLResponse("<h1>Episode not found</h1>", status_code=404)
        summary = await get_summary_by_episode(session, episode_id)
        podcast_name = episode.podcast.name if episode.podcast else "Unknown"
    return templates.TemplateResponse(
        request, "episode.html",
        {
            "episode": episode,
            "summary": summary,
            "podcast_name": podcast_name,
            "active": "digest",
        },
    )


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(
        request, "chat.html", {"active": "chat", "conversation_id": None}
    )


@router.get("/chat/{conversation_id}", response_class=HTMLResponse)
async def chat_page_with_id(request: Request, conversation_id: int):
    return templates.TemplateResponse(
        request, "chat.html", {"active": "chat", "conversation_id": conversation_id}
    )
