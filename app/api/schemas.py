from datetime import datetime

from pydantic import BaseModel, HttpUrl


# ── Request schemas ────────────────────────────────────────────


class PodcastCreate(BaseModel):
    rss_url: str
    name: str | None = None


# ── Response schemas ───────────────────────────────────────────


class PodcastResponse(BaseModel):
    id: int
    name: str
    rss_url: str
    image_url: str | None
    added_at: datetime

    model_config = {"from_attributes": True}


class EpisodeResponse(BaseModel):
    id: int
    podcast_id: int
    guid: str
    title: str
    description: str | None
    published_at: datetime | None
    audio_url: str
    duration_seconds: int | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SummaryResponse(BaseModel):
    id: int
    episode_id: int
    summary_text: str
    key_topics: list[str]
    highlights: list[str]
    listen_score: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DigestItem(BaseModel):
    episode: EpisodeResponse
    podcast_name: str
    summary: SummaryResponse
