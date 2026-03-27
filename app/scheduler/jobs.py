import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.services.pipeline import process_pending_episodes
from app.services.rss import poll_all_feeds, sync_feeds_from_yaml

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def poll_and_process() -> None:
    """Scheduled job: sync feeds, poll for new episodes, then process them."""
    logger.info("Scheduled job started: poll & process")
    try:
        await sync_feeds_from_yaml()
        results = await poll_all_feeds()
        logger.info("Poll results: %s", results)

        processed = await process_pending_episodes()
        logger.info("Scheduled job done: %d episodes processed", processed)
    except Exception:
        logger.exception("Scheduled job failed")


def start_scheduler() -> None:
    """Start the background scheduler with the configured poll interval."""
    scheduler.add_job(
        poll_and_process,
        trigger=IntervalTrigger(hours=settings.poll_interval_hours),
        id="poll_and_process",
        name="Poll RSS feeds and process new episodes",
        replace_existing=True,
    )
    # Run once shortly after startup to catch up on missed episodes
    scheduler.add_job(
        poll_and_process,
        id="poll_and_process_startup",
        name="Startup catch-up poll",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (interval: every %dh, startup run scheduled)", settings.poll_interval_hours)


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
