# 🎙️ AI Podcast Summary Assistant

An automated system that polls podcast RSS feeds, transcribes episodes using Groq Whisper, summarizes them with Groq Llama 3.3 70B, and delivers a daily digest ranked by listen-worthiness — so you can decide which episodes are worth your time without listening to any of them.

Includes a conversational AI chat agent for exploring your podcast library through natural language.

**Live**: [podcast-assistant-app.azurewebsites.net](https://podcast-assistant-app.azurewebsites.net)

---

## Features

- **Automated ingestion** — Polls RSS feeds every 6 hours, detects new episodes by GUID, processes them end-to-end
- **Audio transcription** — Downloads audio, chunks files >25MB, transcribes via Groq Whisper (large-v3-turbo)
- **Structured summaries** — Generates a paragraph summary, 3–5 key topics, 2–3 highlights, and a listen-worthiness score (1–10) via Groq Llama 3.3 70B
- **Daily digest** — Web dashboard showing the last 24 hours of episodes, ranked by score
- **Chat agent** — Conversational interface with tool-calling: search episodes, ask questions about transcripts, manage subscriptions, get personalized recommendations with dual scoring (listen-worthiness + relevance to your objective)
- **MCP server** — Expose podcast tools to AI assistants (Claude Desktop, etc.) via Model Context Protocol
- **Immediate processing** — When you add a podcast, episodes are fetched and processed in the background immediately — no waiting for the next scheduler cycle
- **Responsive UI** — Dark theme, works on desktop, tablet, and mobile

---

## System Design

### High-Level Architecture

```
                    ┌─────────────────────────────┐
                    │     Azure App Service (B1)   │
                    │     Docker Container         │
                    │                              │
  RSS Feeds ──────▶ │  APScheduler (6h) ──▶ RSS   │
                    │  or POST /podcasts    Parser │
                    │         │                    │
                    │         ▼                    │
                    │  Download ──▶ Azure Blob     │ ◀── Temporary staging
                    │         │      (cleaned)     │
                    │         ▼                    │
                    │  Chunk (≤25MB segments)      │
                    │         │                    │
                    │         ▼                    │
                    │  Groq Whisper ──▶ Transcript │ ◀── Groq free tier
                    │         │                    │
                    │         ▼                    │
                    │  Groq Llama 3.3 ──▶ Summary  │
                    │         │           + Score  │
                    │         ▼                    │
                    │  Azure PostgreSQL             │
                    │    │       │       │          │
                    │    ▼       ▼       ▼          │
                    │  REST   Chat    MCP           │
                    │  API    Agent   Server        │
                    │    │       │                  │
                    │    ▼       ▼                  │
                    │  Web UI (Jinja2 + JS)         │
                    └─────────────────────────────┘
```

### Component Responsibilities

| Component         | What it does                         | Key behaviors                                                                                            |
| ----------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| **RSS Service**   | Parses feeds, detects new episodes   | 24h lookback window, GUID-based dedup, SSL cert handling for Acast/CDN domains                           |
| **Audio Service** | Downloads, uploads to blob, chunks   | Streaming download via httpx, pydub for splitting, merges tiny tail chunks (<1s)                         |
| **Transcription** | Sends audio to Groq Whisper          | Exponential backoff (3 retries, 2s/4s/8s), chunks processed sequentially                                 |
| **Summarizer**    | Sends transcript to Llama 3.3 70B    | Structured JSON prompt, truncates transcripts >120k chars, validates output keys, clamps score 1–10      |
| **Pipeline**      | Chains the above steps per episode   | Marks episodes processing→done/failed, always cleans up local files and blob, error-isolated per episode |
| **Scheduler**     | Triggers poll+process on an interval | APScheduler AsyncIO, 6h default, syncs feeds.yaml then polls all DB podcasts                             |
| **Chat Agent**    | Conversational podcast exploration   | 7 tools, max 5 tool-calling rounds per message, SSE streaming, dual scoring, per-conversation objectives |
| **MCP Server**    | Exposes tools for external AI agents | 5 tools (digest, search, summary, add, list), shared CRUD layer                                          |

### Data Flow: New Episode Processing

```
1. Scheduler fires (or user adds podcast)
2. RSS parser fetches feed XML, filters to last 24h
3. GUIDs compared against DB — only new episodes inserted (status: pending)
4. Pipeline picks up pending episodes sequentially:
   a. Download audio via httpx streaming → local /data/ directory
   b. Upload to Azure Blob Storage
   c. If file >25MB: split into ≤25MB chunks with pydub
   d. Each chunk → Groq Whisper API → text transcript
   e. Concatenated transcript → Groq Llama 3.3 70B → JSON (summary, topics, highlights, score)
   f. Summary stored in DB, episode marked "done"
   g. Local files and blob deleted (cleanup always runs, even on error)
5. If any step fails: episode marked "failed" with error message, pipeline moves to next
```

### Data Flow: Chat Message

```
1. User sends message via POST /chat (SSE stream)
2. Conversation loaded (or created), user message saved to DB
3. System prompt built dynamically: base instructions + podcast list + user's objective
4. Message history loaded from DB → Groq API format
5. Tool loop (max 5 rounds):
   a. Call Llama 3.3 70B with tools + history
   b. If model returns tool_calls: execute each, save results, emit SSE tool events
   c. If model returns text: break loop
6. Final text response streamed word-by-word via SSE
7. Complete response saved to DB
```

---

## Behaviors & Edge Cases

### RSS Polling

- **24h lookback**: Only episodes published in the last 24 hours are ingested per poll. Older episodes from newly-added podcasts won't be picked up unless they fall within this window.
- **Immediate poll on add**: When a podcast is added (via API or UI), `poll_feed()` runs immediately followed by `process_pending_episodes()` in a FastAPI `BackgroundTask`. The user sees a loading spinner; episodes appear in the digest once processing completes.
- **feeds.yaml sync**: On each scheduler run, `feeds.yaml` entries are synced into the DB (inserts only, doesn't delete). Podcasts added via UI/API persist in the DB regardless of feeds.yaml.

### Audio Processing

- **Chunk merging**: If a split produces a tail chunk <1 second, it gets merged into the previous chunk. This avoids Whisper errors on near-empty audio.
- **Format detection**: Supports MP3 and M4A. Format is inferred from the Content-Type header or file extension.
- **Blob as staging**: Audio is uploaded to Azure Blob, transcribed, then deleted. The blob container is normally empty. This avoids the 1GB disk limit on App Service B1.

### Transcription & Summarization

- **Rate limit handling**: Whisper calls use exponential backoff (2s → 4s → 8s) with 3 retries. If all fail, the episode is marked `failed` and the pipeline moves on.
- **Transcript truncation**: Transcripts >120k characters (~30k tokens) are truncated before being sent to Llama for summarization. The full transcript is still stored in the DB.
- **Score rubric**: The summarizer prompt includes a detailed 1–10 rubric (1–3: skip, 4–6: skim, 7–8: worth listening, 9–10: must-listen). The model follows it consistently but scores are subjective.

### Chat Agent

- **Tool loop cap**: Maximum 5 tool-calling rounds per message prevents runaway API calls. In practice, most messages need 1–2 rounds.
- **Auto-titling**: The first user message in a conversation is used to generate a title (via separate Llama call).
- **Objective-based personalization**: Each conversation can have an objective (e.g., "I'm interested in neuroscience and AI"). The agent uses this to compute a per-episode relevance score alongside the static listen score.
- **Tool status in UI**: During tool execution, pulsing status pills show which tools are running (e.g., "Searching episodes…").

### Scheduler

- **In-process**: APScheduler runs inside the FastAPI process. On Azure App Service with Always On enabled, the process stays alive. If the process restarts, the scheduler reinitializes on startup — no missed cycles accumulate, but any in-progress processing is interrupted.
- **Sequential processing**: Episodes are processed one at a time to stay within Groq rate limits and avoid concurrent blob operations.

---

## Tradeoffs

### In-Process Scheduler vs. External Job Runner

**Chose**: APScheduler running inside the FastAPI process.

**Why**: Zero infrastructure overhead — no Redis, no Celery worker, no separate cron container. For a single-user personal tool, the simplicity outweighs the downsides.

**Downside**: If the App Service restarts mid-processing, the current episode's pipeline is interrupted (it'll be retried as `pending` on next run — but the blob needs manual cleanup if the process died between upload and delete). No distributed locking — can't scale to multiple instances without double-processing.

### SSE vs. WebSockets for Chat

**Chose**: Server-Sent Events over a single `POST /chat`.

**Why**: Unidirectional streaming (server → client) is simpler to implement and debug. Works through Azure's reverse proxy without additional configuration. FastAPI's `StreamingResponse` makes it straightforward.

**Downside**: Each message requires a new HTTP request from the client. No persistent connection for server-initiated messages (push notifications, etc.). Adequate for a request-response chat pattern but wouldn't scale to real-time collaboration.

### Server-Rendered UI vs. SPA Framework

**Chose**: Jinja2 templates + vanilla JavaScript + CSS.

**Why**: No build step, no npm, no framework overhead. Pages load fast since HTML is rendered server-side. The chat page uses JS for SSE streaming, but everything else is pure server-rendered.

**Downside**: No client-side routing — every page navigation is a full reload. Complex interactivity (like the chat) requires verbose vanilla JS (~650 lines in chat.js). A React/Vue SPA would be more maintainable at larger scale.

### Single-Provider AI (Groq)

**Chose**: Groq for both transcription (Whisper) and summarization/chat (Llama 3.3 70B).

**Why**: One API key, one SDK, entirely free. Groq's inference speed is exceptional — Whisper transcription is near-real-time, Llama responses stream at hundreds of tokens/second.

**Downside**: Single point of failure. If Groq's free tier changes or has an outage, the entire AI pipeline stops. The SDK is locked to Groq's model selection — can't easily swap to GPT-4 or Claude without rewriting the chat tool-calling logic (different function-calling formats).

### Azure Blob as Temporary Staging

**Chose**: Upload audio to Azure Blob Storage, transcribe, then immediately delete.

**Why**: App Service B1 has a 1GB disk limit. Podcast episodes can be 50–100MB each. Using blob as a pass-through avoids disk exhaustion.

**Downside**: Extra latency (upload + download) compared to processing directly from disk. If the process crashes between upload and transcription, orphaned blobs accumulate (though the cost is negligible). No audio replay capability — once deleted, the episode must be re-downloaded to re-transcribe.

### 24-Hour Lookback Window

**Chose**: Only ingest episodes published in the last 24 hours per poll.

**Why**: Prevents the system from downloading and processing an entire podcast's back catalog when a new feed is added, which would hit rate limits and take hours.

**Downside**: If the scheduler is down for >24 hours, episodes published during the gap will be missed. Newly-added podcasts only capture their most recent episode(s), not historical content. The lookback window is hardcoded, not configurable.

### Sequential Episode Processing

**Chose**: Process episodes one at a time, not in parallel.

**Why**: Groq's free tier has strict rate limits (20 RPS for Whisper, 30 RPM for Llama). Sequential processing with backoff keeps us well under limits without needing a token bucket or semaphore.

**Downside**: A 10-episode backlog processes in series, which can take 20–30 minutes. Parallelism would cut this significantly, but risks hitting rate limits and adds complexity.

### No Authentication

**Chose**: The app is currently single-user with no login.

**Why**: Built as a personal tool. Adding auth adds complexity (OAuth flows, session management, per-user data scoping) that wasn't needed for v1.

**Downside**: Anyone with the URL can access the digest, add/remove podcasts, and use the chat. A Google OAuth implementation plan exists (shared content model with per-user subscriptions) but hasn't been implemented.

---

## Getting Started

### Prerequisites

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/download.html) (for audio processing with pydub)
- An Azure account (for PostgreSQL, Blob Storage) or local PostgreSQL
- A [Groq API key](https://console.groq.com/) (free tier)

### Local Setup

```bash
# Clone the repo
git clone <repo-url>
cd ai-podcast-assistant

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials (see Environment Variables below)

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The app will be available at `http://localhost:8000/ui`.

### Environment Variables

| Variable                       | Required | Description                                       |
| ------------------------------ | -------- | ------------------------------------------------- |
| `GROQ_API_KEY`                 | Yes      | Groq API key for Whisper + Llama                  |
| `DATABASE_URL`                 | Yes      | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `AZURE_BLOB_CONNECTION_STRING` | Yes      | Azure Storage account connection string           |
| `AZURE_BLOB_CONTAINER_NAME`    | No       | Blob container name (default: `podcast-audio`)    |
| `POLL_INTERVAL_HOURS`          | No       | Scheduler interval in hours (default: `6`)        |
| `FEEDS_FILE`                   | No       | Path to seed feeds YAML (default: `feeds.yaml`)   |

### Adding Podcasts

Three ways to add podcasts:

1. **Web UI**: Navigate to `/ui/podcasts`, paste an RSS URL, click Add
2. **REST API**: `POST /podcasts` with `{"rss_url": "https://..."}`
3. **feeds.yaml**: Add entries to the YAML file (synced on scheduler runs)

```yaml
# feeds.yaml
feeds:
  - name: "Lex Fridman Podcast"
    rss_url: "https://lexfridman.com/feed/podcast/"
  - name: "Huberman Lab"
    rss_url: "https://feeds.megaphone.fm/hubermanlab"
  - name: "The Daily (NYT)"
    rss_url: "https://feeds.simplecast.com/54nAGcIl"
```

---

## Deployment (Azure)

The app runs as a Docker container on Azure App Service, pulling from Azure Container Registry.

### Azure Resources

| Resource                   | Name                    | SKU          |
| -------------------------- | ----------------------- | ------------ |
| Resource Group             | `rg-podcast-assistant`  | —            |
| PostgreSQL Flexible Server | `podcast-assistant-db`  | B1ms         |
| Storage Account            | `podcastassistantstor`  | Standard LRS |
| Container Registry         | `podcastassistantacr`   | Basic        |
| App Service Plan           | Linux                   | B1           |
| Web App                    | `podcast-assistant-app` | —            |

### Build & Deploy

```bash
# Build and push to ACR
az acr build \
  --registry podcastassistantacr \
  --image podcast-assistant:v1 \
  --file Dockerfile .

# Restart the app (picks up the new image)
az webapp restart \
  --name podcast-assistant-app \
  --resource-group rg-podcast-assistant
```

### App Service Configuration

- **Always On**: Enabled (keeps the process alive for the scheduler)
- **WEBSITES_PORT**: `8000`
- **Application Settings**: All environment variables from the table above

---

## Project Structure

```
ai-podcast-assistant/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI entrypoint + composite lifespan
│   ├── config.py               # pydantic-settings configuration
│   ├── db/
│   │   ├── models.py           # Podcast, Episode, Summary, Conversation, Message
│   │   ├── database.py         # Async engine, session factory, Azure SSL
│   │   └── crud.py             # All database operations
│   ├── services/
│   │   ├── rss.py              # RSS polling (feedparser + certifi)
│   │   ├── audio.py            # Download, blob upload, chunk, cleanup
│   │   ├── transcription.py    # Groq Whisper with retry
│   │   ├── summarizer.py       # Groq Llama 3.3 70B structured output
│   │   ├── pipeline.py         # Episode processing orchestrator
│   │   └── chat.py             # Chat agent with tool-calling + SSE
│   ├── api/
│   │   ├── routes.py           # REST + Chat SSE endpoints
│   │   └── schemas.py          # Pydantic models
│   ├── mcp/
│   │   └── server.py           # FastMCP tools
│   ├── scheduler/
│   │   └── jobs.py             # APScheduler config
│   └── ui/
│       ├── views.py            # Server-rendered routes
│       ├── static/
│       │   ├── chat.js         # Chat client (SSE, markdown, typing indicator)
│       │   └── style.css       # Dark theme, responsive
│       └── templates/
│           ├── base.html       # Layout + nav
│           ├── digest.html     # Daily digest cards
│           ├── podcasts.html   # Subscription management
│           ├── episode.html    # Episode detail view
│           └── chat.html       # Chat interface
├── data/                       # Temporary audio (gitignored)
├── feeds.yaml                  # Seed podcast feeds
├── Dockerfile                  # python:3.11-slim + ffmpeg
├── .dockerignore
├── .env.example
├── requirements.txt
├── Design.md                   # Full design document
└── README.md
```

---

## API Reference

### REST Endpoints

```
GET    /podcasts                  → List all podcasts
POST   /podcasts                  → Add podcast (body: {"rss_url": "..."})
DELETE /podcasts/{id}             → Remove podcast
GET    /episodes                  → List episodes (?podcast_id=&status=)
GET    /episodes/{id}/summary     → Get episode summary
GET    /daily-digest              → Last 24h summaries, ranked by score
POST   /process                   → Trigger manual poll + process
```

### Chat (SSE)

```
POST   /chat                      → Stream chat (body: {"message": "...", "conversation_id": N})
GET    /conversations             → List conversations
POST   /conversations             → Create conversation
GET    /conversations/{id}/messages → Message history
DELETE /conversations/{id}        → Delete conversation
PUT    /conversations/{id}/objective → Set objective
```

### MCP Tools

Connect the MCP server to Claude Desktop or any MCP-compatible client. The server exposes 5 tools: `get_daily_digest`, `search_episodes`, `get_podcast_summary`, `add_podcast`, `list_podcasts`.

---

## Tech Stack

| Layer         | Technology                        |
| ------------- | --------------------------------- |
| Runtime       | Python 3.11                       |
| Framework     | FastAPI + Uvicorn                 |
| Database      | PostgreSQL (asyncpg + SQLAlchemy) |
| Transcription | Groq Whisper large-v3-turbo       |
| Summarization | Groq Llama 3.3 70B Versatile      |
| Chat          | Groq Llama 3.3 70B + Tool Calling |
| Audio         | pydub + ffmpeg                    |
| Storage       | Azure Blob Storage                |
| Scheduling    | APScheduler (AsyncIO)             |
| MCP           | FastMCP                           |
| Frontend      | Jinja2 + vanilla JS + CSS         |
| Deployment    | Docker → ACR → Azure App Service  |

---

## License

Personal project. Not licensed for redistribution.
