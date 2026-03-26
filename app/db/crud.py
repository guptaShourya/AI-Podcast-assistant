from datetime import datetime, timedelta, timezone

from sqlalchemy import String, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Episode, EpisodeStatus, Podcast, Summary


# ── Podcast CRUD ──────────────────────────────────────────────


async def get_all_podcasts(session: AsyncSession) -> list[Podcast]:
    result = await session.execute(select(Podcast).order_by(Podcast.added_at.desc()))
    return list(result.scalars().all())


async def get_podcast_by_rss_url(session: AsyncSession, rss_url: str) -> Podcast | None:
    result = await session.execute(select(Podcast).where(Podcast.rss_url == rss_url))
    return result.scalar_one_or_none()


async def create_podcast(session: AsyncSession, name: str, rss_url: str, image_url: str | None = None) -> Podcast:
    podcast = Podcast(name=name, rss_url=rss_url, image_url=image_url)
    session.add(podcast)
    await session.commit()
    await session.refresh(podcast)
    return podcast


async def delete_podcast(session: AsyncSession, podcast_id: int) -> bool:
    result = await session.execute(select(Podcast).where(Podcast.id == podcast_id))
    podcast = result.scalar_one_or_none()
    if not podcast:
        return False
    await session.delete(podcast)
    await session.commit()
    return True


# ── Episode CRUD ──────────────────────────────────────────────


async def get_existing_guids(session: AsyncSession, guids: list[str]) -> set[str]:
    if not guids:
        return set()
    result = await session.execute(select(Episode.guid).where(Episode.guid.in_(guids)))
    return {row[0] for row in result.all()}


async def create_episodes_bulk(session: AsyncSession, episodes: list[dict]) -> list[Episode]:
    new_episodes = [Episode(**ep) for ep in episodes]
    session.add_all(new_episodes)
    await session.commit()
    for ep in new_episodes:
        await session.refresh(ep)
    return new_episodes


async def get_pending_episodes(session: AsyncSession) -> list[Episode]:
    result = await session.execute(
        select(Episode)
        .where(Episode.status == EpisodeStatus.pending)
        .order_by(Episode.created_at.asc())
    )
    return list(result.scalars().all())


async def update_episode_status(
    session: AsyncSession,
    episode_id: int,
    status: EpisodeStatus,
    error_message: str | None = None,
) -> None:
    result = await session.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()
    if episode:
        episode.status = status
        episode.error_message = error_message
        await session.commit()


async def get_episodes(
    session: AsyncSession,
    podcast_id: int | None = None,
    status: EpisodeStatus | None = None,
) -> list[Episode]:
    query = select(Episode).order_by(Episode.published_at.desc().nullslast())
    if podcast_id is not None:
        query = query.where(Episode.podcast_id == podcast_id)
    if status is not None:
        query = query.where(Episode.status == status)
    result = await session.execute(query)
    return list(result.scalars().all())


# ── Summary CRUD ──────────────────────────────────────────────


async def create_summary(session: AsyncSession, **kwargs) -> Summary:
    summary = Summary(**kwargs)
    session.add(summary)
    await session.commit()
    await session.refresh(summary)
    return summary


async def get_summary_by_episode(session: AsyncSession, episode_id: int) -> Summary | None:
    result = await session.execute(select(Summary).where(Summary.episode_id == episode_id))
    return result.scalar_one_or_none()


async def get_daily_digest(session: AsyncSession) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await session.execute(
        select(Episode)
        .options(selectinload(Episode.summary), selectinload(Episode.podcast))
        .join(Summary)
        .where(Summary.created_at >= since)
        .order_by(Summary.listen_score.desc())
    )
    episodes = result.scalars().all()
    return [
        {
            "episode": ep,
            "podcast": ep.podcast,
            "summary": ep.summary,
        }
        for ep in episodes
        if ep.summary
    ]


async def search_episodes(session: AsyncSession, query: str) -> list[dict]:
    pattern = f"%{query}%"
    result = await session.execute(
        select(Episode)
        .options(selectinload(Episode.summary), selectinload(Episode.podcast))
        .join(Summary)
        .where(
            or_(
                Episode.title.ilike(pattern),
                Summary.summary_text.ilike(pattern),
                Summary.key_topics.cast(String).ilike(pattern),
            )
        )
        .order_by(Summary.listen_score.desc())
    )
    episodes = result.scalars().all()
    return [
        {
            "episode": ep,
            "podcast": ep.podcast,
            "summary": ep.summary,
        }
        for ep in episodes
        if ep.summary
    ]
