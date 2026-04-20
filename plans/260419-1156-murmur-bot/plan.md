---
name: Murmur Bot
status: completed
created: 2026-04-19
updated: 2026-04-19
phases: 4
blockedBy: []
blocks: []
---

# Murmur Bot — Telegram Discussion Capture & Knowledge Bot

Silent listener that captures team discussions, summarizes shared links, and provides AI-powered catch-up, topic tracking, drafting, and decision support via DM.

## Context
- [Brainstorm Report](../reports/brainstorm-260419-1141-telegram-discussion-capture-bot.md)
- [Base Bot Analysis](../reports/researcher-260419-1157-telegram-summarizer-analysis.md)
- [Vertex AI / Gemini 3 Research](../reports/researcher-260419-1340-vertex-ai-gemini-3-research.md)
- Forked from: [telegram_link_summarizer_agent](https://github.com/kargarisaac/telegram_link_summarizer_agent)

## Architecture Overview
```
Telegram Group ──► Murmur Bot (silent capture + link summaries)
                    └── Store all messages → Supabase (Postgres)

User DM ◄──► Murmur Bot (commands + personal sources)
              ├── Group pool (shared)
              ├── Personal pool (per user)
              └── Gemini 3 via Vertex AI (summarize, draft, decide)

DB ──► Cron export ──► NotebookLM (notebooklm-py)

Hosting: GCP Cloud Run | Storage: Supabase (Postgres)
```

## Existing Codebase (Forked)
- **FastAPI + python-telegram-bot v21+** — webhook + polling modes
- **LangGraph + BAML** — link routing + summarization pipeline (5 extractors: web, PDF, X/Twitter, LinkedIn, YouTube)
- **BAML LLM clients** — currently Gemini 2.5 Flash + DeepSeek V3 → upgrade to Gemini 3
- **Content extraction** — Tavily (web), twitterapi.io (X), Playwright+AgentQL (YouTube, LinkedIn), PyMuPDF (PDF)
- **Docker** — Playwright image, `uv` package manager
- **No persistence, no commands, no group capture** — all to be added

## Tech Stack
- Python 3.12+, python-telegram-bot v21+, FastAPI, LangGraph, BAML
- **Gemini 3 only (v1 choice)** — all LLM features use Gemini 3 models. Intentional simplification for this version to reduce integration surface. Not a permanent architecture constraint — the `google-genai` SDK and BAML support model swaps with a config change.
- **Supabase (Postgres)** — source of truth for all data
- Docker + GCP Cloud Run
- `uv` for dependency management (`pyproject.toml`)
- notebooklm-py (Phase 4)

## LLM Strategy (Gemini 3 for v1)

### Models
| Model | API ID | Use Case |
|-------|--------|----------|
| **Gemini 3 Flash** | `gemini-3-flash-preview` | Default for all features — catchup, topics, search, decide |
| **Gemini 3.1 Pro** | `gemini-3.1-pro-preview` | /draft multi-turn (quality matters), complex reasoning |
| **Gemini 3.1 Flash-Lite** | `gemini-3.1-flash-lite-preview` | High-volume bulk ops (reminders, batch summaries) |

### SDK & Auth
- **SDK:** `google-genai` (unified, async via `.aio`, officially recommended)
- **Production (Cloud Run):** Vertex AI + service account + Workload Identity (no JSON key files)
- **Local dev:** `GEMINI_API_KEY` env var (Gemini Developer API for quick iteration)

### Integration Split
- **BAML** (`baml_src/`): Link routing + summarization — upgrade `clients.baml` to `gemini-3-flash-preview`
- **google-genai SDK** (`summarizer.py`): New features — catchup, topics, draft, decide (async, structured output, thinking mode)

## Design Principles
- **Supabase = single source of truth** for messages, links, personal memory, reminders, command state
- **Privacy before prompts** — app-layer filtering is primary control; enforce shared/private boundary before prompt construction, not after
- **Start simple, improve later** — /topics and /topic don't need perfect clustering on day one
- **Grounded outputs** — /draft and /decide cite where outputs come from
- **Unified memory model** — reminders and NotebookLM export plug into same stored data, no side systems
- **Consistent Telegram ID naming** — `tg_msg_id`, `tg_chat_id`, `tg_user_id` across all tables
- **Per-user per-chat state** — catchup tracking scoped to (user, chat) for multi-group support
- **Keep existing pipeline intact** — BAML routing/summarization upgraded to Gemini 3; new features use google-genai SDK

## Phases

| # | Phase | Status | Priority |
|---|-------|--------|----------|
| 1 | [Foundation](phase-01-foundation.md) | completed | Critical |
| 2 | [Core Usability](phase-02-core-usability.md) | completed | High |
| 3 | [Structured Intelligence](phase-03-structured-intelligence.md) | completed | High |
| 4 | [Extended Workflows](phase-04-extended-workflows.md) | completed | Medium |

## Implementation Sequence
1. **Foundation** — Supabase schema, group message capture, link summary storage, shared vs private memory boundary, /start, upgrade BAML to Gemini 3
2. **Core Usability** — /catchup, /search, personal memory save flow (using google-genai SDK)
3. **Structured Intelligence** — /topics, /topic, /draft, /decide
4. **Extended Workflows** — reminders, NotebookLM export

## Key Risks
| Risk | Mitigation |
|------|------------|
| notebooklm-py unofficial | Fallback: Notion API or markdown export |
| X/Twitter extraction flaky | Base bot already handles via Tavily; add fallback scraper |
| Grok share links need JS | Test; fallback to screenshot + OCR |
| LLM costs | Flash-Lite for bulk, Flash for default, Pro only for /draft |
| Gemini 3 models in preview | Stable enough for production; pin model IDs, monitor deprecations |
| BAML no native Vertex AI provider | Use `google-ai` provider with API key; SDK for Vertex AI features |

## Acceptance Criteria (Testable)
- `/catchup` returns a grouped digest covering all messages since the user's last catchup, in <10 seconds
- Every link shared in group is auto-summarized and stored in `link_summaries` within 30 seconds
- `/topics` returns 3-8 labeled threads from the last 48h of messages
- `/topic <name>` returns a synthesis with [username, date] citations for at least 80% of points
- `/draft <topic>` enters multi-turn mode; user can exchange 5+ messages before `/done`
- `/decide <topic>` returns structured output: options, arguments, evidence, gaps — all with citations
- `/search <keyword>` returns results labeled [GROUP] or [PERSONAL]; User A never sees User B's personal sources
- Reminders DM users at their configured frequency; content matches what `/catchup` would return
- `/export` uploads topic documents to NotebookLM; re-export of unchanged content is skipped (content_hash dedup)
- Bot responds to `/start` in DM within 2 seconds with full command list
