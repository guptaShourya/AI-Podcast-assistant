import asyncio
import json
import logging

from groq import AsyncGroq

from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncGroq(api_key=settings.groq_api_key)

MAX_RETRIES = 3
BASE_DELAY = 2

SYSTEM_PROMPT = """You are a podcast analysis assistant. Given a podcast transcript, produce a structured JSON summary.

Return ONLY valid JSON with these exact keys:
{
  "summary": "A concise one-paragraph summary of the episode (3-5 sentences).",
  "key_topics": ["topic1", "topic2", "topic3"],
  "highlights": ["Notable quote or insight 1", "Notable quote or insight 2"],
  "listen_score": 7
}

Rules for listen_score (1-10):
- 1-3: Filler content, repetitive, low substance
- 4-5: Average, some useful info but not must-listen
- 6-7: Good episode, solid insights, worth listening
- 8-9: Excellent, highly informative or compelling
- 10: Exceptional, landmark episode

Be honest and critical with scoring. Most episodes should score 5-7."""


async def summarize_transcript(transcript: str, episode_title: str = "") -> dict:
    """Send transcript to Groq Llama 3.3 70B and return structured summary."""
    # Truncate very long transcripts to stay within context limits
    max_chars = 120_000  # ~30k tokens
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n\n[Transcript truncated]"

    user_message = f"Episode: {episode_title}\n\nTranscript:\n{transcript}"

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            raw = response.choices[0].message.content
            result = json.loads(raw)

            # Validate required keys
            required = {"summary", "key_topics", "highlights", "listen_score"}
            if not required.issubset(result.keys()):
                missing = required - result.keys()
                raise ValueError(f"Missing keys in LLM response: {missing}")

            # Clamp score
            result["listen_score"] = max(1, min(10, int(result["listen_score"])))

            return result

        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            delay = BASE_DELAY * (2 ** attempt)
            logger.warning("Summarization attempt %d failed: %s. Retrying in %ds...", attempt + 1, e, delay)
            await asyncio.sleep(delay)
