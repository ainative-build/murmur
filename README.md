# Murmur Bot

Silent listener that captures team discussions, summarizes shared links, and provides AI-powered catch-up, topic tracking, drafting, and decision support via DM.

> Forked from [telegram_link_summarizer_agent](https://github.com/kargarisaac/telegram_link_summarizer_agent)

## What it does

**In group chats:** Murmur silently captures every message — text, links, voice messages, photos, and file attachments. Auto-summarizes shared links (articles, tweets, PDFs, YouTube transcripts, LinkedIn posts, Grok conversations, Spotify podcasts) and file attachments (PDF, DOCX, TXT, MD).

**In DMs:** Members interact with Murmur to catch up, search, brainstorm, and make decisions — all grounded in real team context. Send voice messages, files, or links to save them as personal sources.

### Commands

| Command | Description | Status |
|---------|-------------|--------|
| `/start` | Welcome message + command list | ✅ |
| `/catchup` | Digest of discussions since your last check-in | ✅ |
| `/search <keyword>` | Search messages and links | ✅ |
| `/topics` | List active discussion threads | ✅ |
| `/topic <name>` | Deep dive on a specific topic | ✅ |
| `/decide <topic>` | Structured decision view (options, arguments, evidence) | ✅ |
| `/remind` | Configure reminder frequency | ✅ |
| `/export` | Export topics to markdown files | ✅ |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Bot framework | python-telegram-bot v21+ |
| Web server | FastAPI + Uvicorn |
| Link pipeline | LangGraph + BAML (routing + summarization) |
| LLM | Gemini 3 via `google-genai` SDK (Vertex AI in production) |
| Database | Supabase (Postgres) |
| Content extraction | TinyFish (Grok, X Articles, GitHub), Tavily (web), twitterapi.io (X), youtube-transcript-api (YouTube), Playwright+AgentQL (LinkedIn), PyMuPDF (PDF), python-docx (DOCX) |
| Voice/audio | Gemini 3 Flash audio transcription (OGG Opus from Telegram) |
| Podcast metadata | Spotify Web API (client credentials) with oEmbed fallback |
| Package manager | uv |
| Deployment | Docker + GCP Cloud Run |

## Setup

### 1. Clone and install

```bash
git clone https://github.com/ainative-build/murmur.git
cd murmur
uv sync
playwright install
```

### 2. Configure environment

Create `.env` in project root:

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key

# Gemini (for BAML link pipeline + future features)
GEMINI_API_KEY=your_gemini_api_key

# Content extraction tools
TAVILY_API_KEY=your_tavily_key
TWITTER_API_IO_KEY=your_twitterapi_io_key
AGENTQL_API_KEY=your_agentql_key
TINYFISH_API_KEY=your_tinyfish_key

# Optional: Spotify (for podcast episode metadata)
# SPOTIFY_CLIENT_ID=your_spotify_client_id
# SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

# Optional: DeepSeek as BAML fallback
DEEPSEEK_API_KEY=your_deepseek_key

# Webhook (production only — not needed for polling)
# WEBHOOK_URL=https://your-cloud-run-url
# WEBHOOK_SECRET_PATH=webhook
# TELEGRAM_WEBHOOK_SECRET_TOKEN=your_secret

# Polling mode (local dev)
USE_POLLING=true
```

### 3. Set up Supabase

Run the migration against your Supabase project:

```bash
# Via Supabase dashboard: SQL Editor → paste contents of:
cat supabase/migrations/001_init_schema.sql
```

Run all migrations (001-008) in order. Creates 7 tables: `messages`, `link_summaries`, `personal_sources`, `user_chat_state`, `users`, `exports`, `scheduled_deletions`, plus `feedback`.

### 4. BotFather setup

1. Create bot via [@BotFather](https://t.me/BotFather) → get token
2. `/setprivacy` → **Disable** (bot must see all group messages)
3. `/setcommands`:
   ```
   start - Welcome and help
   catchup - Get digest of recent discussions
   search - Search messages and links
   topics - List active discussion threads
   topic - Deep dive on a specific topic
   draft - Brainstorm with AI using team context
   decide - Structured decision view on a topic
   ```
4. Add bot to your group chat

## Running

### Local (polling mode)

```bash
USE_POLLING=true uv run python bot.py
```

### Local (webhook via ngrok)

```bash
# Terminal 1: start bot
uv run uvicorn bot:app --host 0.0.0.0 --port 8080

# Terminal 2: expose via ngrok
ngrok http 8080
# Copy the HTTPS URL → set as WEBHOOK_URL in .env → restart bot
```

### Docker

```bash
chmod +x ./scripts/run_docker.sh
./scripts/run_docker.sh
```

### Cloud Run

```bash
chmod +x ./scripts/deploy_cloud_run.sh
./scripts/deploy_cloud_run.sh
```

> **Note:** Set `WEBHOOK_URL` explicitly for Cloud Run — auto-inference is not supported.

Health check: `curl http://localhost:8080/health`

## Project Structure

```
murmur/
├── bot.py              # FastAPI + PTB: handlers, lifespan, webhook
├── agent.py            # LangGraph pipeline: link routing + summarization
├── config.py           # Centralized env var loading
├── db.py               # Supabase client wrapper
├── commands.py         # DM command handlers (/start, /catchup, /search, etc.)
├── summarizer.py       # Gemini 3 LLM calls (catchup, topics, decide, draft)
├── personal.py         # Personal source processing (DM links, voice, files)
├── url_normalize.py    # URL normalization for dedup
├── baml_src/           # BAML LLM configs (Gemini 3 Flash + DeepSeek fallback)
├── tools/              # Content extractors
│   ├── tinyfish_fetcher.py   # TinyFish Web Fetch (Grok, X Articles, GitHub)
│   ├── voice_transcriber.py  # Gemini audio transcription
│   ├── file_extractor.py     # PDF, DOCX, TXT, MD text extraction
│   ├── spotify_scraper.py    # Spotify Web API + oEmbed metadata
│   ├── search.py             # Tavily web extraction
│   ├── pdf_handler.py        # PyMuPDF PDF handler
│   └── ...                   # Twitter, LinkedIn, YouTube scrapers
├── supabase/           # Database migrations (001-008)
├── tests/              # 263 unit tests
├── scripts/            # Deploy + integration test scripts
└── docs/               # Architecture, code standards, codebase summary
```

## Testing

```bash
# Run all tests
uv run python -m pytest tests/ -v

# With coverage
uv run python -m pytest tests/ --cov=. --cov-report=html
```

## Architecture

```
Telegram Group ──► Murmur Bot (silent capture + link summaries)
                    └── Store all messages → Supabase (Postgres)

User DM ◄──► Murmur Bot (commands)
              ├── Group pool (shared)
              ├── Personal pool (private per user)
              └── Gemini 3 (summarize, draft, decide)
```

**Privacy model:** Group messages are shared; personal sources are private. App-layer `WHERE tg_user_id = ?` is the primary privacy control. Row Level Security on `personal_sources` is defense-in-depth.

## Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| 1. Foundation | Group capture, Supabase, /start, Gemini 3 | ✅ Complete |
| 2. Core Usability | /catchup, /search, personal memory | ✅ Complete |
| 3. Structured Intelligence | /topics, /topic, /decide | ✅ Complete |
| 4. Extended Workflows | Reminders, markdown export | ✅ Complete |

| 5. Rich Media | Voice, files, YouTube transcripts, Spotify, TinyFish | ✅ Complete |

### Planned
- `/draft <topic>` — Multi-turn AI brainstorm with team context (ConversationHandler UX needs refinement)
- **pgvector + Gemini context caching** — Semantic search via Supabase pgvector (embed messages → retrieve relevant 20-30 instead of brute-force 200+). Context caching for repeated system prompts (75% token savings on cached portion). Expected: 40% cost reduction, 50x faster for repeated queries.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
