import json
import logging
from typing import AsyncGenerator

import feedparser
from groq import AsyncGroq

from app.config import settings
from app.db import crud
from app.db.database import async_session
from app.db.models import MessageRole

logger = logging.getLogger(__name__)

client = AsyncGroq(api_key=settings.groq_api_key)
MODEL = "llama-3.3-70b-versatile"
MAX_TOOL_ROUNDS = 5

# ── Tool definitions (Groq function-calling format) ───────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_daily_digest",
            "description": "Get today's podcast episode summaries ranked by listen-worthiness score (1-10). Call this when the user asks for their daily update, what's new, or what to listen to.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_episodes",
            "description": "Search across podcast episode titles, summaries, topics, and transcripts by keyword. Use this to find episodes about a specific topic or answer questions from podcast content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or phrase",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_episode_detail",
            "description": "Get the full summary, key topics, highlights, and transcript excerpt for a specific episode by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "episode_id": {
                        "type": "integer",
                        "description": "The episode ID",
                    }
                },
                "required": ["episode_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_podcasts",
            "description": "List all podcast subscriptions with their categories.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_podcast",
            "description": "Subscribe to a new podcast by RSS feed URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rss_url": {
                        "type": "string",
                        "description": "The RSS feed URL of the podcast",
                    }
                },
                "required": ["rss_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_podcast",
            "description": "Unsubscribe from a podcast by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "podcast_id": {
                        "type": "integer",
                        "description": "The podcast ID to remove",
                    }
                },
                "required": ["podcast_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_podcast_category",
            "description": "Set or update the category for a podcast (e.g. tech, news, health, business, science, culture, education, finance, other).",
            "parameters": {
                "type": "object",
                "properties": {
                    "podcast_id": {
                        "type": "integer",
                        "description": "The podcast ID",
                    },
                    "category": {
                        "type": "string",
                        "description": "The category to assign",
                    },
                },
                "required": ["podcast_id", "category"],
            },
        },
    },
]


# ── Tool execution ────────────────────────────────────────────


async def _exec_tool(name: str, args: dict) -> str:
    """Execute a tool by name and return a string result."""
    async with async_session() as session:
        if name == "get_daily_digest":
            items = await crud.get_daily_digest(session)
            if not items:
                return "No new episode summaries in the last 24 hours."
            lines = []
            for item in items:
                ep, s, p = item["episode"], item["summary"], item["podcast"]
                lines.append(
                    f"[{s.listen_score}/10] {ep.title} ({p.name})\n"
                    f"  Summary: {s.summary_text}\n"
                    f"  Topics: {', '.join(s.key_topics)}\n"
                    f"  Highlights: {'; '.join(s.highlights)}\n"
                    f"  Episode ID: {ep.id}"
                )
            return f"Daily Digest ({len(items)} episodes):\n\n" + "\n\n---\n\n".join(lines)

        elif name == "search_episodes":
            query = args.get("query", "")
            items = await crud.search_episodes(session, query)
            if not items:
                return f"No episodes found matching '{query}'."
            lines = []
            for item in items:
                ep, s, p = item["episode"], item["summary"], item["podcast"]
                lines.append(
                    f"[{s.listen_score}/10] {ep.title} ({p.name})\n"
                    f"  Summary: {s.summary_text}\n"
                    f"  Topics: {', '.join(s.key_topics)}\n"
                    f"  Episode ID: {ep.id}"
                )
            return f"Found {len(items)} episode(s):\n\n" + "\n\n---\n\n".join(lines)

        elif name == "get_episode_detail":
            episode_id = args.get("episode_id")
            summary = await crud.get_summary_by_episode(session, episode_id)
            if not summary:
                return f"No summary found for episode {episode_id}."
            return (
                f"Listen Score: {summary.listen_score}/10\n"
                f"Summary: {summary.summary_text}\n"
                f"Key Topics: {', '.join(summary.key_topics)}\n"
                f"Highlights:\n" + "\n".join(f"- {h}" for h in summary.highlights) + "\n"
                f"Transcript excerpt ({len(summary.transcript_text)} chars total):\n"
                f"{summary.transcript_text[:3000]}"
            )

        elif name == "list_podcasts":
            podcasts = await crud.get_all_podcasts(session)
            if not podcasts:
                return "No podcast subscriptions yet."
            lines = [
                f"- {p.name} (id={p.id}, category={p.category or 'uncategorized'}): {p.rss_url}"
                for p in podcasts
            ]
            return f"Subscriptions ({len(podcasts)}):\n" + "\n".join(lines)

        elif name == "add_podcast":
            rss_url = args.get("rss_url", "")
            existing = await crud.get_podcast_by_rss_url(session, rss_url)
            if existing:
                return f"Already subscribed to '{existing.name}'."
            feed = feedparser.parse(rss_url)
            name = feed.feed.get("title", rss_url)
            image_url = feed.feed.get("image", {}).get("href")
            podcast = await crud.create_podcast(session, name=name, rss_url=rss_url, image_url=image_url)
            return f"Subscribed to '{podcast.name}' (id={podcast.id}). New episodes will be picked up on the next poll."

        elif name == "remove_podcast":
            podcast_id = args.get("podcast_id")
            deleted = await crud.delete_podcast(session, podcast_id)
            return "Podcast removed." if deleted else "Podcast not found."

        elif name == "set_podcast_category":
            podcast_id = args.get("podcast_id")
            category = args.get("category", "")
            updated = await crud.update_podcast_category(session, podcast_id, category)
            return f"Category set to '{category}'." if updated else "Podcast not found."

    return f"Unknown tool: {name}"


# ── System prompt builder ─────────────────────────────────────

BASE_SYSTEM_PROMPT = """\
You are a helpful podcast assistant. You help the user stay on top of their podcast subscriptions.

Your capabilities:
- Show today's daily digest of new episodes ranked by listen-worthiness
- Search episode summaries and transcripts by keyword
- Get detailed summaries, highlights, and transcripts for specific episodes
- Manage podcast subscriptions (add, remove, list)
- Set categories for podcasts

When answering questions about podcast content, ALWAYS use the search_episodes or get_episode_detail tools first to ground your answer in actual podcast data. If no relevant podcast content is found, you may answer from your general knowledge but clearly state that the answer is not from a podcast.

FORMATTING RULES — Follow these strictly for every response:
- Use **bold** for episode titles, podcast names, and key terms
- For the daily digest or episode lists, use this EXACT card format for each episode:

> **[SCORE/10] Episode Title** · Relevance: RELEVANCE/10
> *Podcast Name* · Duration
>
> One-sentence summary of what this episode covers.
>
> **Key Topics:** topic1, topic2, topic3
>
> **Why it matters:** One sentence connecting this to the user's interests/objective.

- The SCORE is the general listen-worthiness from the database. The RELEVANCE score (1-10) is YOUR assessment of how useful this episode is for the user's chat objective. If the chat has no objective, omit the Relevance score.
- Sort episodes by Relevance score (highest first) when an objective is set, not by listen score.

- Use `---` between episode cards
- For highlights or key takeaways, use numbered lists (1. 2. 3.) not bullets
- Keep summaries to 1-2 sentences max — punchy and scannable
- Use ### headings to organize sections (e.g. ### Today's Digest, ### Recommendations)
- For Q&A answers from podcast content, quote the relevant insight with > blockquotes, then give your synthesis
- Never dump raw data — always interpret and frame it for the user
- End digest responses with a brief **TL;DR** line summarizing the top recommendation"""


async def _build_system_prompt(objective: str | None) -> str:
    """Build system prompt with optional objective and current subscriptions."""
    parts = [BASE_SYSTEM_PROMPT]

    # Add current subscriptions context
    async with async_session() as session:
        podcasts = await crud.get_all_podcasts(session)
    if podcasts:
        sub_lines = [f"- {p.name} (category: {p.category or 'uncategorized'})" for p in podcasts]
        parts.append(f"\nThe user's current podcast subscriptions:\n" + "\n".join(sub_lines))

    # Add objective if set
    if objective:
        parts.append(
            f"\n**IMPORTANT — Chat Objective**: The user has configured this chat with a specific goal: \"{objective}\"\n"
            f"Tailor ALL your responses, recommendations, and summaries to be relevant to this objective. "
            f"When presenting the daily digest or search results, prioritize and frame content through the lens of this objective. "
            f"Highlight how podcast content connects to this goal."
        )

    return "\n".join(parts)


# ── Message history builder ───────────────────────────────────


def _db_messages_to_groq(messages) -> list[dict]:
    """Convert DB Message objects to Groq API message format."""
    result = []
    for msg in messages:
        if msg.role == MessageRole.user:
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == MessageRole.assistant:
            entry = {"role": "assistant"}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
                entry["content"] = msg.content or ""
            else:
                entry["content"] = msg.content or ""
            result.append(entry)
        elif msg.role == MessageRole.tool:
            result.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id or "",
                "content": msg.content or "",
            })
    return result


# ── Chat orchestration ────────────────────────────────────────


async def chat_stream(
    conversation_id: int, user_message: str
) -> AsyncGenerator[str, None]:
    """
    Run the chat loop: save user message, call LLM with tools,
    execute tools as needed, then stream the final text response.
    Yields text chunks as they arrive.
    """
    async with async_session() as session:
        # Get conversation for objective
        conv = await crud.get_conversation(session, conversation_id)
        if not conv:
            yield "Error: conversation not found."
            return
        objective = conv.objective

        # Save user message
        await crud.add_message(session, conversation_id, MessageRole.user, content=user_message)

        # Auto-title from first message
        if conv.title == "New Chat":
            title = user_message[:50] + ("..." if len(user_message) > 50 else "")
            await crud.update_conversation_title(session, conversation_id, title)

        # Load full history
        db_messages = await crud.get_conversation_messages(session, conversation_id)

    # Build messages for Groq
    system_prompt = await _build_system_prompt(objective)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(_db_messages_to_groq(db_messages))

    # Tool loop
    for _round in range(MAX_TOOL_ROUNDS):
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.4,
        )

        choice = response.choices[0]

        if choice.finish_reason == "tool_calls" or (choice.message.tool_calls):
            # Save the assistant message with tool calls
            tc_data = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.message.tool_calls
            ]
            async with async_session() as session:
                await crud.add_message(
                    session, conversation_id, MessageRole.assistant,
                    content=choice.message.content,
                    tool_calls=tc_data,
                )

            # Execute each tool and yield status
            assistant_msg = {"role": "assistant", "content": choice.message.content or "", "tool_calls": tc_data}
            messages.append(assistant_msg)

            for tc in choice.message.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                # Yield tool status to UI
                yield f"__TOOL__{fn_name}\n"

                result = await _exec_tool(fn_name, fn_args)

                # Save tool result message
                async with async_session() as session:
                    await crud.add_message(
                        session, conversation_id, MessageRole.tool,
                        content=result, tool_call_id=tc.id,
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            # Final text response — stream it
            break
    else:
        # Exceeded max rounds, do a final call without tools
        pass

    # Stream the final response
    stream = await client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="none",
        temperature=0.4,
        stream=True,
    )

    full_response = []
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            full_response.append(delta.content)
            yield delta.content

    # Save the complete assistant response
    final_text = "".join(full_response)
    async with async_session() as session:
        await crud.add_message(
            session, conversation_id, MessageRole.assistant,
            content=final_text,
        )
