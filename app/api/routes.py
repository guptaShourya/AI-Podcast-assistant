import logging

import feedparser
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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
from app.services.pipeline import process_pending_episodes
from app.services.chat import chat_stream

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
    poll_results = await poll_all_feeds()
    processed = await process_pending_episodes()
    return {
        "message": "Processing complete",
        "new_episodes_found": poll_results,
        "episodes_processed": processed,
    }


# ── Chat ──────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str
    objective: str | None = None


class ConversationCreate(BaseModel):
    title: str = "New Chat"
    objective: str | None = None


@router.get("/conversations")
async def list_conversations(session: AsyncSession = Depends(get_session)):
    convs = await crud.get_conversations(session)
    return [
        {
            "id": c.id,
            "title": c.title,
            "objective": c.objective,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in convs
    ]


@router.post("/conversations")
async def create_conversation(body: ConversationCreate, session: AsyncSession = Depends(get_session)):
    conv = await crud.create_conversation(session, title=body.title, objective=body.objective)
    return {"id": conv.id, "title": conv.title, "objective": conv.objective}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, session: AsyncSession = Depends(get_session)):
    conv = await crud.get_conversation(session, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await crud.get_conversation_messages(session, conversation_id)
    return [
        {
            "id": m.id,
            "role": m.role.value,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "tool_call_id": m.tool_call_id,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int, session: AsyncSession = Depends(get_session)):
    deleted = await crud.delete_conversation(session, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.put("/conversations/{conversation_id}/objective")
async def update_objective(conversation_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    objective = body.get("objective", "")
    updated = await crud.update_conversation_objective(session, conversation_id, objective)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@router.post("/chat")
async def chat_endpoint(body: ChatRequest, session: AsyncSession = Depends(get_session)):
    conversation_id = body.conversation_id

    # Create conversation if needed
    if not conversation_id:
        conv = await crud.create_conversation(
            session, title="New Chat", objective=body.objective
        )
        conversation_id = conv.id

    async def event_stream():
        # Send conversation_id as first event
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conversation_id})}\n\n"

        async for chunk in chat_stream(conversation_id, body.message):
            if chunk.startswith("__TOOL__"):
                tool_name = chunk.replace("__TOOL__", "").strip()
                yield f"data: {json.dumps({'type': 'tool', 'name': tool_name})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

        yield "data: [DONE]\n\n"

    import json
    return StreamingResponse(event_stream(), media_type="text/event-stream")
