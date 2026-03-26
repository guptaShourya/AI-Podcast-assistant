import logging

from app.db import crud
from app.db.database import async_session
from app.db.models import EpisodeStatus
from app.services.audio import (
    chunk_audio,
    cleanup_local_files,
    delete_blob,
    download_audio,
    upload_to_blob,
)
from app.services.summarizer import summarize_transcript
from app.services.transcription import transcribe_chunks

logger = logging.getLogger(__name__)


async def process_episode(episode_id: int, audio_url: str, title: str) -> None:
    """Full pipeline for one episode: download → chunk → transcribe → summarize → store."""
    local_path = None
    chunk_paths = []
    blob_name = f"episode_{episode_id}.mp3"

    try:
        # Mark as processing
        async with async_session() as session:
            await crud.update_episode_status(session, episode_id, EpisodeStatus.processing)

        # Step 1: Download audio
        logger.info("[Episode %d] Downloading audio...", episode_id)
        local_path = await download_audio(audio_url, episode_id)

        # Step 2: Upload to blob (staging)
        logger.info("[Episode %d] Uploading to blob storage...", episode_id)
        await upload_to_blob(local_path, blob_name)

        # Step 3: Chunk if needed
        logger.info("[Episode %d] Checking if chunking needed...", episode_id)
        chunk_paths = chunk_audio(local_path)

        # Step 4: Transcribe
        logger.info("[Episode %d] Transcribing %d chunk(s)...", episode_id, len(chunk_paths))
        transcript = await transcribe_chunks(chunk_paths)

        if not transcript.strip():
            raise ValueError("Transcription returned empty text")

        # Step 5: Summarize
        logger.info("[Episode %d] Summarizing transcript (%d chars)...", episode_id, len(transcript))
        summary_data = await summarize_transcript(transcript, title)

        # Step 6: Store results
        async with async_session() as session:
            await crud.create_summary(
                session,
                episode_id=episode_id,
                transcript_text=transcript,
                summary_text=summary_data["summary"],
                key_topics=summary_data["key_topics"],
                highlights=summary_data["highlights"],
                listen_score=summary_data["listen_score"],
            )
            await crud.update_episode_status(session, episode_id, EpisodeStatus.done)

        logger.info("[Episode %d] ✓ Done (score: %d/10)", episode_id, summary_data["listen_score"])

    except Exception as e:
        logger.exception("[Episode %d] Failed: %s", episode_id, e)
        async with async_session() as session:
            await crud.update_episode_status(
                session, episode_id, EpisodeStatus.failed, error_message=str(e)[:500]
            )

    finally:
        # Cleanup: delete local files and blob
        all_files = list(chunk_paths)
        if local_path and local_path not in chunk_paths:
            all_files.append(local_path)
        cleanup_local_files(*all_files)

        try:
            await delete_blob(blob_name)
        except Exception:
            logger.debug("Blob %s may not exist, skipping cleanup", blob_name)


async def process_pending_episodes() -> int:
    """Process all pending episodes. Returns count of episodes processed."""
    async with async_session() as session:
        pending = await crud.get_pending_episodes(session)

    if not pending:
        logger.info("No pending episodes to process")
        return 0

    logger.info("Processing %d pending episode(s)...", len(pending))

    processed = 0
    for episode in pending:
        await process_episode(episode.id, episode.audio_url, episode.title)
        processed += 1

    return processed
