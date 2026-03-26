# AI Podcast Summary Assistant — Design Document

> **Author**: Shourya  
> **Date**: 25 March 2026  
> **Last Updated**: 26 March 2026  
> **Status**: Implemented & Deployed

## Overview

A FastAPI service that automatically polls podcast RSS feeds, transcribes episodes via Groq Whisper, generates structured summaries via Groq Llama 3.3 70B, and delivers a ranked daily digest — so you can quickly decide which episodes are worth your time. Includes a conversational AI chat agent for exploring your podcast library through natural language.

Hosted on Azure App Service. Entire AI stack runs on Groq's free tier. Infrastructure covered by Azure credits.

**Live**: `https://podcast-assistant-app.azurewebsites.net`

---

## Problem Statement

Keeping up with multiple podcast subscriptions is time-consuming. New episodes drop daily across shows, and there's no efficient way to triage which ones deserve a full listen without skimming each one manually.

**Solution**: An automated pipeline that ingests, transcribes, and summarizes every new episode — then ranks them by a listen-worthiness score (1–10), giving you a scannable daily digest. A chat agent lets you ask questions about episodes, search across transcripts, and manage subscriptions conversationally.

---

## Tech Stack

| Component     | Technology                        | Why                                                  |
| ------------- | --------------------------------- | ---------------------------------------------------- |
| Language      | Python 3.11                       | Best ecosystem for audio/AI libs                     |
| Framework     | FastAPI (async)                   | High-performance async API, great DX                 |
| Transcription | Groq Whisper API (large-v3-turbo) | Free tier: 20 RPS / 2K RPD                           |
| Summarization | Groq Llama 3.3 70B Versatile      | Free tier: 30 RPM / 14,400 RPD                       |
| Chat Agent    | Groq Llama 3.3 70B + Tool Calling | Function calling for DB queries, SSE streaming       |
| Database      | Azure PostgreSQL Flexible Server  | B1ms, production-grade, SSL-encrypted                |
| Hosting       | Azure App Service (B1 Linux)      | Always-on, container deployment via ACR              |
| Container     | Docker → Azure Container Registry | Reproducible builds, managed image hosting           |
| Audio Storage | Azure Blob Storage                | Temporary audio staging, cleaned after transcription |
| Scheduler     | APScheduler (AsyncIO)             | In-process, no broker dependency                     |
| MCP Server    | FastMCP (Python MCP SDK)          | Expose tools to AI assistants (Claude Desktop, etc.) |
| Frontend      | Jinja2 + vanilla JS + CSS         | Server-rendered UI with SSE streaming for chat       |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Azure App Service (B1 Linux)                    │
│                      Docker container via ACR                        │
│                                                                      │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────────────┐       │
│  │ Scheduler │───▶│  RSS Parser  │───▶│  New Episode Detect   │       │
│  │ (6h poll) │    │ (feedparser) │    │  (GUID dedup vs DB)   │       │
│  └──────────┘    └──────────────┘    └──────────┬────────────┘       │
│                                                  │                    │
│  ┌──────────┐                                    │                    │
│  │ Add Pod- │─── poll_feed() ───────────────────▶│                    │
│  │ cast API │    + BackgroundTasks                │                    │
│  └──────────┘                                    ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │   Audio Downloader    │       │
│                                      │ (httpx → Azure Blob)  │       │
│                                      └──────────┬────────────┘       │
│                                                  │                    │
│                                                  ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │   Audio Chunker       │       │
│                                      │ (pydub, ≤25MB chunks) │       │
│                                      └──────────┬────────────┘       │
│                                                  │                    │
│                                                  ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │   Groq Whisper API    │       │
│                                      │ (large-v3-turbo)      │──▶ Transcript
│                                      └──────────┬────────────┘       │
│                                                  │                    │
│                                                  ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │  Groq Llama 3.3 70B   │       │
│                                      │  (summarize + score)   │──▶ Summary +
│                                      └──────────┬────────────┘    Topics +
│                                                  │                Score (1-10)
│                                                  ▼                    │
│                                      ┌───────────────────────┐       │
│                                      │  Azure PostgreSQL     │       │
│                                      │  (Flexible Server)    │       │
│                                      └──┬─────┬─────┬────────┘       │
│                                         │     │     │                 │
│                          ┌──────────────┘     │     └──────────┐      │
│                          ▼                    ▼                ▼      │
│               ┌──────────────┐    ┌────────────────┐  ┌────────────┐ │
│               │  REST API    │    │  Chat Agent    │  │ MCP Server │ │
│               │  (FastAPI)   │    │  (Tool Calling │  │ (FastMCP)  │ │
│               └──────┬───────┘    │   + SSE)       │  └────────────┘ │
│                      │            └───────┬────────┘                  │
│                      ▼                    ▼                           │
│               ┌────────────────────────────────────┐                 │
│               │           Web UI (Jinja2)          │                 │
│               │  Digest · Podcasts · Chat · Detail │                 │
│               └────────────────────────────────────┘                 │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ai-podcast-assistant/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + composite lifespan (DB, scheduler, MCP)
│   ├── config.py               # Settings via pydantic-settings (.env)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy models: Podcast, Episode, Summary, Conversation, Message
│   │   ├── database.py         # Async engine + session factory (Azure SSL handling)
│   │   └── crud.py             # All database operations (podcast, episode, summary, conversation)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── rss.py              # RSS feed parser + polling (feedparser, certifi SSL)
│   │   ├── audio.py            # Download → blob upload → chunk → cleanup
│   │   ├── transcription.py    # Groq Whisper API client (retry + backoff)
│   │   ├── summarizer.py       # Groq Llama 3.3 70B structured summarization
│   │   ├── pipeline.py         # Orchestrator: download → transcribe → summarize → store
│   │   └── chat.py             # Chat agent: Groq tool-calling + SSE streaming
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py           # REST + Chat SSE endpoints (BackgroundTasks on add)
│   │   └── schemas.py          # Pydantic request/response models
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── server.py           # FastMCP tools for AI assistant integration
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py             # APScheduler job: poll + process every 6h
│   └── ui/
│       ├── views.py            # Server-rendered routes (Jinja2)
│       ├── static/
│       │   ├── chat.js         # Chat client: SSE, markdown, typing indicator
│       │   └── style.css       # Dark theme, responsive, animations
│       └── templates/
│           ├── base.html       # Layout: nav, hamburger menu, content block
│           ├── digest.html     # Daily digest: scored episode cards
│           ├── podcasts.html   # Subscription management + add form with loader
│           ├── episode.html    # Full episode detail: summary, topics, transcript
│           └── chat.html       # Chat UI: sidebar, messages, objective, modal
├── data/                       # Temporary audio downloads (gitignored)
├── feeds.yaml                  # Seed podcast RSS feeds
├── requirements.txt
├── Dockerfile                  # python:3.11-slim + ffmpeg
├── .dockerignore
├── .env.example
├── .gitignore
└── README.md
```

---

## Database Schema

### Podcast

| Column    | Type         | Constraints        |
| --------- | ------------ | ------------------ |
| id        | Integer (PK) | Auto-increment     |
| name      | String       | Not null           |
| rss_url   | String       | Not null, unique   |
| image_url | String       | Nullable           |
| category  | String       | Nullable           |
| added_at  | DateTime     | Default: now (UTC) |

### Episode

| Column           | Type                                        | Constraints                 |
| ---------------- | ------------------------------------------- | --------------------------- |
| id               | Integer (PK)                                | Auto-increment              |
| podcast_id       | Integer (FK → Podcast.id)                   | Not null, on delete cascade |
| guid             | String                                      | Not null, unique            |
| title            | String                                      | Not null                    |
| description      | Text                                        | Nullable                    |
| published_at     | DateTime                                    | Nullable                    |
| audio_url        | String                                      | Not null                    |
| duration_seconds | Integer                                     | Nullable                    |
| status           | Enum (pending / processing / done / failed) | Default: pending            |
| error_message    | Text                                        | Nullable                    |
| created_at       | DateTime                                    | Default: now (UTC)          |

### Summary

| Column          | Type                      | Constraints        |
| --------------- | ------------------------- | ------------------ |
| id              | Integer (PK)              | Auto-increment     |
| episode_id      | Integer (FK → Episode.id) | Not null, unique   |
| transcript_text | Text                      | Not null           |
| summary_text    | Text                      | Not null           |
| key_topics      | JSON (list of strings)    | Not null           |
| highlights      | JSON (list of strings)    | Not null           |
| listen_score    | Integer (1–10)            | Not null           |
| created_at      | DateTime                  | Default: now (UTC) |

### Conversation

| Column     | Type         | Constraints        |
| ---------- | ------------ | ------------------ |
| id         | Integer (PK) | Auto-increment     |
| title      | String       | Not null           |
| objective  | Text         | Nullable           |
| created_at | DateTime     | Default: now (UTC) |
| updated_at | DateTime     | Auto-updated       |

### Message

| Column          | Type                           | Constraints                 |
| --------------- | ------------------------------ | --------------------------- |
| id              | Integer (PK)                   | Auto-increment              |
| conversation_id | Integer (FK → Conversation.id) | Not null, on delete cascade |
| role            | Enum (user / assistant / tool) | Not null                    |
| content         | Text                           | Nullable                    |
| tool_calls      | JSON                           | Nullable                    |
| tool_call_id    | String                         | Nullable                    |
| created_at      | DateTime                       | Default: now (UTC)          |

---

## API Endpoints

### REST API

| Method   | Endpoint                 | Description                                     |
| -------- | ------------------------ | ----------------------------------------------- |
| `GET`    | `/podcasts`              | List all subscribed podcasts                    |
| `POST`   | `/podcasts`              | Subscribe + auto-poll + background process      |
| `DELETE` | `/podcasts/{id}`         | Remove a podcast and all its episodes           |
| `GET`    | `/episodes`              | List episodes (filter by podcast_id, status)    |
| `GET`    | `/episodes/{id}/summary` | Get full summary for an episode                 |
| `GET`    | `/daily-digest`          | Summaries from last 24h, ranked by listen score |
| `POST`   | `/process`               | Manually trigger sync + poll + process pipeline |

### Chat API (SSE)

| Method   | Endpoint                        | Description                                       |
| -------- | ------------------------------- | ------------------------------------------------- |
| `POST`   | `/chat`                         | Stream chat response (SSE: meta/tool/text events) |
| `GET`    | `/conversations`                | List all conversations                            |
| `POST`   | `/conversations`                | Create conversation with optional objective       |
| `GET`    | `/conversations/{id}/messages`  | Get message history                               |
| `DELETE` | `/conversations/{id}`           | Delete conversation                               |
| `PUT`    | `/conversations/{id}/objective` | Update conversation objective                     |

### MCP Tools

| Tool                           | Description                                      |
| ------------------------------ | ------------------------------------------------ |
| `get_daily_digest()`           | Today's episode summaries ranked by listen score |
| `search_episodes(query: str)`  | Keyword search across summaries and transcripts  |
| `get_podcast_summary(id: int)` | Full summary for a specific episode              |
| `add_podcast(rss_url: str)`    | Subscribe to a new podcast                       |
| `list_podcasts()`              | List all subscriptions                           |

### Web UI Routes

| Route              | Page                                             |
| ------------------ | ------------------------------------------------ |
| `/ui`              | Daily digest — episode cards ranked by score     |
| `/ui/podcasts`     | Manage subscriptions (add/remove)                |
| `/ui/episode/{id}` | Full episode detail: summary, topics, transcript |
| `/ui/chat`         | Chat interface (new conversation)                |
| `/ui/chat/{id}`    | Chat interface (resume conversation)             |

---

## Chat Agent

The chat agent provides a conversational interface to the podcast library using Groq Llama 3.3 70B with function calling.

### Capabilities

- Browse and search the daily digest
- Full-text search across episode titles, summaries, topics, and transcripts
- Drill into episode details (full summary, highlights, transcript)
- Add/remove podcast subscriptions
- Categorize podcasts
- Personalized responses based on a per-conversation objective (e.g., "I'm interested in AI and neuroscience")

### Tool Definitions (7)

| Tool                   | Parameters                       | Description                         |
| ---------------------- | -------------------------------- | ----------------------------------- |
| `get_daily_digest`     | —                                | Last 24h summaries, ranked by score |
| `search_episodes`      | `query: str`                     | ILIKE search across all text fields |
| `get_episode_detail`   | `episode_id: int`                | Full summary + transcript           |
| `list_podcasts`        | —                                | All subscriptions with categories   |
| `add_podcast`          | `rss_url: str`                   | Subscribe to new feed               |
| `remove_podcast`       | `podcast_id: int`                | Unsubscribe from feed               |
| `set_podcast_category` | `podcast_id: int, category: str` | Update podcast category             |

### Dual Scoring

The chat agent displays two scores per episode:

- **Listen Score (1–10)**: Pre-computed by the summarizer, reflects general listen-worthiness
- **Relevance Score**: Computed at chat time based on the user's stated objective

### Streaming

Responses are delivered via Server-Sent Events (SSE):

- `type: meta` — Conversation ID and metadata
- `type: tool` — Tool execution status updates (shown as pulsing pills in the UI)
- `type: text` — Streamed text chunks with rich markdown formatting

### Tool Loop

The agent runs up to 5 sequential tool-calling rounds per message. Each round: call Llama → execute tool calls → feed results back → repeat until a text response is generated.

---

## Implementation Phases

All phases are **complete and deployed**.

### Phase 1: Foundation ✅

- Project scaffolding, `requirements.txt`, `config.py` with pydantic-settings
- SQLAlchemy async models (Podcast, Episode, Summary) with asyncpg
- RSS service with feedparser, GUID dedup, 24h lookback window
- `feeds.yaml` seed feeds

### Phase 2: Audio Processing Pipeline ✅

- Async streaming download via httpx → Azure Blob Storage (MP3/M4A)
- Audio chunking with pydub (≤25MB per chunk, tiny-chunk merging)
- Groq Whisper transcription with exponential backoff (3 retries)
- Groq Llama 3.3 70B structured summarization (JSON output: summary, topics, highlights, score)
- Pipeline orchestrator with error isolation and cleanup

### Phase 3: Scheduler + API ✅

- APScheduler AsyncIO (6h interval), configurable via `POLL_INTERVAL_HOURS`
- Full REST API with Pydantic schemas
- Manual trigger endpoint (`POST /process`)

### Phase 4: MCP Server ✅

- 5 FastMCP tools mounted on the same app
- Shared service layer with REST API

### Phase 5: Web UI ✅

- Jinja2 server-rendered dashboard (dark theme)
- Pages: Digest, Podcasts, Episode Detail
- Score badges (color-coded), topic tags, transcript viewer

### Phase 6: Chat Agent ✅

- Conversation/Message models
- Groq Llama 3.3 70B with function-calling orchestration
- 7 tools, dual scoring (listen + relevance), SSE streaming
- Rich markdown rendering in the browser (custom parser)
- Objective-based personalization per conversation

### Phase 7: UX Polish + Deployment ✅

- Responsive design: hamburger nav, mobile sidebar overlay, tablet/phone breakpoints
- Typing indicator (animated bouncing dots)
- Podcast add spinner/loader with disabled button state
- Background processing on podcast add (BackgroundTasks)
- Docker containerization (python:3.11-slim + ffmpeg)
- Azure deployment: ACR → App Service (B1 Linux, Always On)

---

## Key Design Decisions

| Decision                                           | Rationale                                                                    |
| -------------------------------------------------- | ---------------------------------------------------------------------------- |
| **Groq for all AI** (Whisper + Llama 3.3 70B)      | Single provider, entirely free, one API key                                  |
| **Azure PostgreSQL** over SQLite                   | Production-grade, deployed alongside app, SSL-encrypted                      |
| **Azure Blob Storage** for audio staging           | Upload → transcribe → delete. Avoids App Service 1GB disk limits             |
| **APScheduler (in-process)** over Celery           | No Redis/broker needed, sufficient for single-instance personal use          |
| **SSE** over WebSockets for chat                   | Simpler (unidirectional server→client), works through Azure proxies          |
| **Tool-calling loop** (max 5 rounds)               | Lets the agent chain multiple DB queries per user message without runaway    |
| **Dual scoring** (listen + relevance)              | Listen score is static (computed once); relevance is dynamic per-user intent |
| **Background processing on add**                   | Episodes are transcribed/summarized immediately, no 6h wait                  |
| **Audio deleted post-transcription**               | Transcripts stored in DB; blob is temporary staging only                     |
| **Server-rendered UI + vanilla JS**                | No build step, no framework overhead, fast initial loads                     |
| **Docker + ACR** over GitHub Actions deploy        | Single `az acr build` command, managed image registry                        |
| **feeds.yaml + REST API + UI** for feed management | Three ways to manage feeds: bulk config, API, or browser                     |

---

## Azure Infrastructure

| Resource                   | SKU / Config                  | Region     |
| -------------------------- | ----------------------------- | ---------- |
| Resource Group             | `rg-podcast-assistant`        | Central US |
| PostgreSQL Flexible Server | B1ms, 32GB storage            | Central US |
| Storage Account            | `podcastassistantstor`        | Central US |
| Blob Container             | `podcast-audio`               | —          |
| Container Registry         | Basic (`podcastassistantacr`) | Central US |
| App Service Plan           | B1 Linux                      | Central US |
| Web App                    | `podcast-assistant-app`       | Central US |

**App Service Config**: Always On enabled, `WEBSITES_PORT=8000`, environment variables set via Application Settings.

### Cost Estimate

| Resource                   | Monthly Cost            |
| -------------------------- | ----------------------- |
| Groq (Whisper + Llama 3.3) | **$0** (free tier)      |
| App Service B1             | ~$13                    |
| PostgreSQL Flexible B1ms   | ~$15                    |
| Container Registry Basic   | ~$5                     |
| Blob Storage               | <$1                     |
| **Total**                  | **~$34 of $150 budget** |

---

## Groq Free Tier Capacity Analysis

**Whisper (transcription)**:

- Limit: 2,000 requests/day, 20 requests/second
- A 60-min episode at 128kbps ≈ 60MB → ~3 chunks → 3 requests
- 10 new episodes/day → ~30 requests → **1.5% of daily limit**

**Llama 3.3 70B (summarization + chat)**:

- Limit: 14,400 requests/day, 30 requests/minute
- Summarization: 1 request per episode
- Chat: ~2–6 requests per user message (tool loop rounds)
- 10 episodes + 50 chat messages/day → ~310 requests → **2.2% of daily limit**

Both limits provide **massive headroom** for personal use.

---

## Scope

**Implemented**: RSS polling, audio transcription, LLM summarization, listen-worthiness scoring, REST API, MCP server, web UI (responsive), conversational chat agent with tool-calling, dual scoring, SSE streaming, Docker deployment, Azure infrastructure

**Not implemented**: User authentication (Google OAuth plan exists), email digests, podcast discovery/recommendation, mobile app, multi-user support, episode playback
