# AI Podcast Summary Assistant — Design Document

> **Author**: Shourya  
> **Date**: 25 March 2026  
> **Status**: Draft

## Overview

A FastAPI backend service that automatically polls podcast RSS feeds, transcribes new episodes via Groq Whisper API, generates structured summaries via Groq Llama 3.3 70B, and delivers a daily digest ranked by "listen-worthiness" — so you can quickly decide which episodes are worth your time.

Hosted on Azure App Service. Entire AI stack is free (Groq free tier). Infrastructure covered by $150/mo Azure credits.

---

## Problem Statement

Keeping up with multiple podcast subscriptions is time-consuming. New episodes drop daily across shows, and there's no efficient way to triage which ones deserve a full listen without skimming each one manually.

**Solution**: An automated pipeline that ingests, transcribes, and summarizes every new episode — then ranks them by a listen-worthiness score (1-10), giving you a scannable daily digest.

---

## Tech Stack

| Component     | Technology                         | Why                                                  |
| ------------- | ---------------------------------- | ---------------------------------------------------- |
| Language      | Python 3.12+                       | Best ecosystem for audio/AI libs                     |
| Framework     | FastAPI (async)                    | High-performance async API, great DX                 |
| Transcription | Groq Whisper API (large-v3-turbo)  | Free tier: 20 RPS / 2K RPD                           |
| Summarization | Groq Llama 3.3 70B                 | Free tier: 30 RPM / 14,400 RPD                       |
| Database      | Azure PostgreSQL Flexible Server   | Free tier (750h/mo B1ms), production-grade           |
| Hosting       | Azure App Service (B1)             | Always-on, GitHub Actions CI/CD, ~$13/mo             |
| Audio Storage | Azure Blob Storage                 | Temporary audio staging, <$1/mo                      |
| Scheduler     | APScheduler                        | Lightweight, no broker dependency                    |
| MCP Server    | FastMCP (Python MCP SDK)           | Expose tools to AI assistants (Claude Desktop, etc.) |
| Frontend      | Jinja2 templates served by FastAPI | Minimal, server-rendered UI                          |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Azure App Service (B1)                      │
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │ Scheduler │───▶│  RSS Parser  │───▶│  New Episode Detect  │   │
│  │ (6h poll) │    │ (feedparser) │    │  (compare vs DB)     │   │
│  └──────────┘    └──────────────┘    └──────────┬───────────┘   │
│                                                  │               │
│                                                  ▼               │
│                                      ┌──────────────────────┐   │
│                                      │   Audio Downloader   │   │
│                                      │ (httpx → Azure Blob) │   │
│                                      └──────────┬───────────┘   │
│                                                  │               │
│                                                  ▼               │
│                                      ┌──────────────────────┐   │
│                                      │   Audio Chunker      │   │
│                                      │ (pydub, ≤25MB each)  │   │
│                                      └──────────┬───────────┘   │
│                                                  │               │
│                                                  ▼               │
│                                      ┌──────────────────────┐   │
│                                      │   Groq Whisper API   │   │
│                                      │ (large-v3-turbo)     │──▶ Transcript
│                                      └──────────┬───────────┘   │
│                                                  │               │
│                                                  ▼               │
│                                      ┌──────────────────────┐   │
│                                      │  Groq Llama 3.3 70B  │   │
│                                      │  (summarization)     │──▶ Summary + Topics
│                                      └──────────┬───────────┘     + Score (1-10)
│                                                  │               │
│                                                  ▼               │
│                                      ┌──────────────────────┐   │
│                                      │  Azure PostgreSQL    │   │
│                                      │  (Flexible Server)   │   │
│                                      └───┬──────────┬───────┘   │
│                                          │          │            │
│                              ┌───────────┘          └──────┐     │
│                              ▼                             ▼     │
│                    ┌──────────────┐              ┌────────────┐  │
│                    │  REST API    │              │ MCP Server │  │
│                    │  (FastAPI)   │              │ (FastMCP)  │  │
│                    └──────┬───────┘              └────────────┘  │
│                           │                                      │
│                           ▼                                      │
│                    ┌──────────────┐                               │
│                    │   Web UI     │                               │
│                    │  (Jinja2)    │                               │
│                    └──────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ai-podcast-assistant/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app + lifespan (scheduler init)
│   ├── config.py               # Settings via pydantic-settings
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy models: Podcast, Episode, Summary
│   │   ├── database.py         # Async engine + session factory
│   │   └── crud.py             # Database operations
│   ├── services/
│   │   ├── __init__.py
│   │   ├── rss.py              # RSS feed parser (feedparser)
│   │   ├── audio.py            # Download + chunk audio files
│   │   ├── transcription.py    # Groq Whisper API client
│   │   ├── summarizer.py       # Groq Llama 3.3 70B summarization
│   │   └── pipeline.py         # Orchestrator: RSS → download → transcribe → summarize → store
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py           # REST endpoints
│   │   └── schemas.py          # Pydantic request/response models
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── server.py           # MCP server exposing tools
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py             # APScheduler job definitions
│   └── ui/
│       └── templates/          # Jinja2 templates for web UI
│           ├── base.html
│           ├── digest.html
│           ├── podcasts.html
│           └── episode.html
├── data/                       # Temporary audio downloads (gitignored)
├── feeds.yaml                  # User's podcast RSS feed list
├── requirements.txt
├── .env.example                # GROQ_API_KEY, AZURE_PG_CONNECTION_STRING, AZURE_BLOB_CONNECTION_STRING
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
| listen_score    | Integer (1-10)            | Not null           |
| created_at      | DateTime                  | Default: now (UTC) |

---

## API Endpoints

### REST API

| Method   | Endpoint                 | Description                                     |
| -------- | ------------------------ | ----------------------------------------------- |
| `GET`    | `/podcasts`              | List all subscribed podcasts                    |
| `POST`   | `/podcasts`              | Subscribe to a new podcast (body: `{rss_url}`)  |
| `DELETE` | `/podcasts/{id}`         | Remove a podcast subscription                   |
| `GET`    | `/episodes`              | List episodes (filter by podcast, date, status) |
| `GET`    | `/episodes/{id}/summary` | Get full summary for an episode                 |
| `GET`    | `/daily-digest`          | Summaries from last 24h, ranked by listen score |
| `POST`   | `/process`               | Manually trigger the processing pipeline        |

### MCP Tools

| Tool                           | Description                                      |
| ------------------------------ | ------------------------------------------------ |
| `get_daily_digest()`           | Today's episode summaries ranked by listen score |
| `search_episodes(query: str)`  | Keyword search across summaries                  |
| `get_podcast_summary(id: int)` | Full summary for a specific episode              |
| `add_podcast(rss_url: str)`    | Subscribe to a new podcast                       |
| `list_podcasts()`              | List all subscriptions                           |

---

## Implementation Phases

### Phase 1: Foundation — Data Layer + RSS Ingestion

1. **Project scaffolding** — Directory structure, `requirements.txt`, `.env.example`, `config.py` with pydantic-settings
2. **Database models** — SQLAlchemy async models for Podcast, Episode, Summary using asyncpg driver
3. **RSS service** — Parse feeds from `feeds.yaml`, detect new episodes by GUID comparison against DB, insert as `pending`
4. **Feed config** — `feeds.yaml` with `{name, rss_url}` entries

### Phase 2: Audio Processing Pipeline

5. **Audio downloader** — Async streaming download via httpx → Azure Blob Storage. Handle MP3/M4A formats
6. **Audio chunker** — Split files >25MB into ≤25MB segments using pydub
7. **Groq transcription service** — Send audio chunks to Groq Whisper API, concatenate transcripts, exponential backoff for rate limits
8. **Groq summarization service** — Structured prompt to Llama 3.3 70B requesting: one-paragraph summary, key topics list, notable quotes/highlights, listen-worthiness score (1-10)
9. **Pipeline orchestrator** — Chains steps 5→8. Fetches pending episodes, processes each, updates DB status. Errors mark episode as `failed` and continue to next

### Phase 3: Scheduler + API

10. **Scheduler setup** — APScheduler with configurable interval (default: 6 hours). Triggers RSS poll → pipeline for new episodes
11. **REST API endpoints** — All routes from the API table above, with Pydantic request/response schemas
12. **Pydantic schemas** — Typed models for all request/response payloads

### Phase 4: MCP Server

13. **FastMCP server** — Expose all MCP tools from the table above. Connects to the same DB and service layer as the REST API

### Phase 5: Web UI

14. **Jinja2 dashboard** — Three pages:
    - **Home / Digest**: Today's episodes as cards (summary, topics, listen score, link to original)
    - **Podcasts**: Manage subscriptions (add/remove)
    - **Episode detail**: Full summary, transcript, metadata

### Phase 6: Polish

15. **Cleanup logic** — Delete audio from Blob Storage after transcription completes
16. **README** — Setup instructions, architecture diagram, environment variable reference

---

## Key Design Decisions

| Decision                                      | Rationale                                                             |
| --------------------------------------------- | --------------------------------------------------------------------- |
| **Groq for all AI** (Whisper + Llama 3.3 70B) | Single provider, entirely free, one API key to manage                 |
| **Azure PostgreSQL** over SQLite              | Production-grade, deployed, better resume signal, backed by free tier |
| **Azure App Service (B1)**                    | Always-on with GitHub Actions CI/CD, ~$13/mo from credits             |
| **Azure Blob Storage** for audio staging      | Upload → transcribe → delete. Avoids App Service disk limits          |
| **APScheduler** over Celery                   | No Redis/broker dependency, sufficient for personal scale             |
| **feeds.yaml + REST API** for feed management | Flexible — bulk configure via file or manage via API/UI               |
| **Listen-worthiness score (1-10)**            | Core UX differentiator. Pre-ranked digest saves decision time         |
| **Audio deleted post-transcription**          | Transcripts stored in DB; no storage bloat                            |

---

## Azure Cost Estimate

| Resource                   | Monthly Cost            |
| -------------------------- | ----------------------- |
| Groq (Whisper + Llama 3.3) | **$0** (free tier)      |
| App Service B1             | ~$13                    |
| PostgreSQL Flexible B1ms   | ~$15 (or free tier)     |
| Blob Storage               | <$1                     |
| **Total**                  | **~$30 of $150 budget** |

Remaining ~$120/mo available for scaling, experimentation, or added Azure services.

---

## Groq Free Tier Capacity Analysis

**Whisper (transcription)**:

- Limit: 2,000 requests/day, 20 requests/second
- A 60-min episode at 128kbps ≈ 60MB → ~3 chunks (25MB each) → 3 requests
- 10 new episodes/day → ~30 requests → **1.5% of daily limit**

**Llama 3.3 70B (summarization)**:

- Limit: 14,400 requests/day, 30 requests/minute
- 1 request per episode (transcript → summary)
- 10 new episodes/day → 10 requests → **0.07% of daily limit**

Both limits provide **massive headroom** for personal use.

---

## Verification Plan

| #   | Test                                                             | Expected Result                                             |
| --- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| 1   | Add 2-3 test RSS feeds (e.g., Lex Fridman, a daily news podcast) | Feeds stored in DB                                          |
| 2   | Run RSS parser                                                   | New episodes detected and inserted with `status=pending`    |
| 3   | Trigger pipeline manually (`POST /process`)                      | Full flow: download → transcribe → summarize → store        |
| 4   | `GET /daily-digest`                                              | Structured JSON with summaries, topics, and listen scores   |
| 5   | Connect MCP server to Claude Desktop                             | "What are my new podcast episodes?" invokes tools correctly |
| 6   | Open web UI                                                      | Dashboard renders episode cards with scores                 |
| 7   | Wait for scheduler auto-trigger                                  | New episodes processed without manual intervention          |
| 8   | Use an invalid audio URL                                         | Episode marked as `failed`, pipeline continues to next      |

---

## Scope

**Included**: RSS polling, audio transcription, LLM summarization, listen-worthiness scoring, REST API, MCP server, basic web UI, podcast subscription management

**Excluded**: User authentication, email digests, podcast discovery/search, mobile app, multi-user support, episode playback
