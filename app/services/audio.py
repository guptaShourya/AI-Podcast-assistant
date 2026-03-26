import logging
import os
from pathlib import Path

import certifi
import httpx
from azure.storage.blob.aio import BlobServiceClient

from app.config import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

MAX_CHUNK_BYTES = 25 * 1024 * 1024  # 25MB Groq Whisper limit


def _blob_service() -> BlobServiceClient:
    """Create a BlobServiceClient with proper SSL context."""
    return BlobServiceClient.from_connection_string(
        settings.azure_blob_connection_string,
        connection_verify=certifi.where(),
    )


async def download_audio(audio_url: str, episode_id: int) -> Path:
    """Download audio file to local disk. Returns the local file path."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        response = await client.get(audio_url)
        response.raise_for_status()

    # Determine extension from content-type or URL
    content_type = response.headers.get("content-type", "")
    if "mp4" in content_type or "m4a" in content_type:
        ext = ".m4a"
    elif "mpeg" in content_type or "mp3" in content_type:
        ext = ".mp3"
    else:
        ext = Path(audio_url.split("?")[0]).suffix or ".mp3"

    local_path = DATA_DIR / f"episode_{episode_id}{ext}"
    local_path.write_bytes(response.content)
    logger.info("Downloaded %s → %s (%.1f MB)", audio_url, local_path, local_path.stat().st_size / 1e6)
    return local_path


async def upload_to_blob(local_path: Path, blob_name: str) -> str:
    """Upload a local file to Azure Blob Storage. Returns the blob URL."""
    blob_service = _blob_service()
    async with blob_service:
        container = blob_service.get_container_client(settings.azure_blob_container_name)
        blob = container.get_blob_client(blob_name)
        with open(local_path, "rb") as f:
            await blob.upload_blob(f, overwrite=True)
    logger.info("Uploaded %s → blob:%s", local_path.name, blob_name)
    return blob.url


async def delete_blob(blob_name: str) -> None:
    """Delete a blob from Azure Blob Storage."""
    blob_service = _blob_service()
    async with blob_service:
        container = blob_service.get_container_client(settings.azure_blob_container_name)
        blob = container.get_blob_client(blob_name)
        await blob.delete_blob(delete_snapshots="include")
    logger.info("Deleted blob: %s", blob_name)


def chunk_audio(local_path: Path) -> list[Path]:
    """Split audio into ≤25MB chunks using pydub. Returns list of chunk paths."""
    file_size = local_path.stat().st_size
    if file_size <= MAX_CHUNK_BYTES:
        logger.info("Audio %s is %.1f MB, no chunking needed", local_path.name, file_size / 1e6)
        return [local_path]

    from pydub import AudioSegment

    ext = local_path.suffix.lstrip(".")
    audio = AudioSegment.from_file(str(local_path), format=ext if ext != "m4a" else "mp4")

    # Estimate chunk duration based on file size ratio
    total_ms = len(audio)
    num_chunks = (file_size // MAX_CHUNK_BYTES) + 1
    chunk_ms = total_ms // num_chunks

    MIN_CHUNK_MS = 1000  # Minimum 1 second per chunk

    chunks = []
    for i in range(0, total_ms, chunk_ms):
        segment = audio[i : i + chunk_ms]
        if len(segment) < MIN_CHUNK_MS and chunks:
            # Append tiny remainder to the last chunk instead of creating a new one
            prev_path = chunks[-1]
            prev_segment = AudioSegment.from_mp3(str(prev_path))
            combined = prev_segment + segment
            combined.export(str(prev_path), format="mp3")
        else:
            chunk_path = local_path.parent / f"{local_path.stem}_chunk{len(chunks)}.mp3"
            segment.export(str(chunk_path), format="mp3")
            chunks.append(chunk_path)

    logger.info("Split %s into %d chunks", local_path.name, len(chunks))
    return chunks


def cleanup_local_files(*paths: Path) -> None:
    """Remove local audio files after processing."""
    for p in paths:
        try:
            if p.exists():
                p.unlink()
        except OSError as e:
            logger.warning("Failed to delete %s: %s", p, e)
