import asyncio
import logging
from pathlib import Path

from groq import AsyncGroq

from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncGroq(api_key=settings.groq_api_key)

# Groq Whisper free tier: 20 RPS, 2000 RPD
MAX_RETRIES = 3
BASE_DELAY = 2  # seconds


async def transcribe_file(file_path: Path) -> str:
    """Transcribe a single audio file via Groq Whisper API with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            with open(file_path, "rb") as f:
                response = await client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=(file_path.name, f),
                    response_format="text",
                )
            return response.strip()
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            delay = BASE_DELAY * (2 ** attempt)
            logger.warning("Transcription attempt %d failed: %s. Retrying in %ds...", attempt + 1, e, delay)
            await asyncio.sleep(delay)


async def transcribe_chunks(chunk_paths: list[Path]) -> str:
    """Transcribe multiple audio chunks sequentially and concatenate results."""
    transcripts = []
    for i, chunk in enumerate(chunk_paths):
        logger.info("Transcribing chunk %d/%d: %s", i + 1, len(chunk_paths), chunk.name)
        text = await transcribe_file(chunk)
        transcripts.append(text)
    return "\n\n".join(transcripts)
