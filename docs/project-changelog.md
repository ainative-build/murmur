# Project Changelog

**Format:** [Unreleased] versions first, then release history.  
**Dates:** UTC timezone.

---

## [Unreleased] — 2026-04-26

### Added
- **AI Provider Abstraction Layer** (`src/providers/`)
  - Abstract `Provider` base class with retry + fallback semantics
  - `GeminiProvider` — Gemini 3 Flash/Pro for text, image, file, voice modalities
  - `MiniMaxProvider` — MiniMax M2.7 for text, image, file, voice modalities
  - Factory function `get_provider(Feature)` with env-driven modality routing
  - Per-modality env vars: `AI_PROVIDER_TEXT`, `AI_PROVIDER_IMAGE`, `AI_PROVIDER_FILE`, `AI_PROVIDER_VOICE`
  - Global fallback: `AI_PROVIDER` (default: `gemini`)

- **Prompt Module Extraction** (`src/ai/prompts/`)
  - Extracted prompt builders from monolithic `summarizer.py` for reusability
  - Modules: `catchup`, `topics`, `topic_detail`, `decide`, `draft`, `reminder`
  - Each module returns (system_prompt, user_prompt) tuple

- **Usage Telemetry**
  - Structured JSON logging: `{"event": "provider_usage", "provider": "<name>", "feature": "<feature>", "input_tokens": N, "output_tokens": M}`
  - Enables cost tracking per provider + modality via Cloud Logging queries

- **81 Unit + Integration Tests** (Phase 6 carryover)
  - Provider interface contracts validated
  - Error handling + retry logic verified
  - GeminiProvider and MiniMaxProvider both tested
  - Total test count: 352 (263 existing + 81 new)

### Changed
- **summarizer.py Refactoring**
  - LOC: 401 → 175 (56% reduction via prompt extraction)
  - All `generate_*` functions now use `get_provider(Feature.TEXT)` instead of direct `genai` imports
  - `get_genai_client()` preserved as backward-compat re-export (points to `GeminiProvider._client`)
  - `config` module still exported for test patches
  - **Public API unchanged** — existing callers (commands.py, agent.py, tests) require no modifications

- **tools/voice_transcriber.py**
  - Now delegates to `get_provider(Feature.VOICE)` instead of direct Gemini API calls
  - Supports both Gemini (async) and MiniMax (polling) transcription modes

- **bot._analyze_image()**
  - Delegates to `get_provider(Feature.IMAGE)` for image analysis
  - No longer hardcoded to Gemini Vision API

### Fixed
- MiniMax STT polling edge case: fixed 2s interval + 30s ceiling (prevents 60s+ hangs if polling times out)
- Provider retry logic now only retries on transient errors (429, 503, timeout), not hard failures (400, 401, 403)

### Notes
- **BAML routing + file summarization remain Gemini-pinned** in this release
  - `RouteRequest` and `SummarizeContent` still call Gemini 3 Flash/Pro via BAML
  - Migration to provider abstraction tracked in Phase 9 (separate plan)
  - Reason: BAML does not yet support MiniMax client definitions; evaluated for future
  
- **VIDEO feature hard-pinned to Gemini**
  - MiniMax does not support video input (design constraint)
  - All YouTube link processing continues via Gemini (no env var override)

- **No breaking changes**
  - Default `AI_PROVIDER=gemini` — behavior identical to prior releases until env vars flipped
  - All existing imports (`from summarizer import generate_catchup`, etc.) still work
  - Tests that patch `summarizer.config` or `summarizer.get_genai_client` continue to pass

### Documentation
- Updated `docs/system-architecture.md` with new "AI Provider Layer" section
- Updated `docs/code-standards.md` with AI provider integration rule
- Updated `docs/codebase-summary.md` with `src/providers/` and `src/ai/prompts/` module details
- Updated `README.md` tech stack to reflect dual-provider support
- Added "Switching Providers (Cloud Run)" section to README (env-only, no rebuild)
- Created `docs/development-roadmap.md` with phase history and upcoming work
- Created this changelog

---

## [0.5.0] — 2026-04-25 (Phase 5 & 6)

### Added
- Rich media support (Phase 5)
  - Voice transcription via Gemini 3 Flash audio API (OGG Opus from Telegram)
  - File extraction (PDF, DOCX, TXT, MD) via tool_file_extractor.py
  - YouTube transcript caching (youtube-transcript-api)
  - Spotify podcast metadata (Web API + oEmbed fallback)
  - TinyFish integration (Grok, X Articles, GitHub)

- Comprehensive test coverage (Phase 6)
  - 81 new unit + integration tests for provider layer
  - Live smoke tests on staging (MiniMax modalities)
  - Total: 352 tests (up from 271)

### Changed
- tools/ subdirectory expanded with rich media extractors
- agent.py updated to route to new media handlers

---

## [0.4.0] — 2026-04-23 (Phase 4)

### Added
- `/remind` command — Configurable reminder digests
- `/export` command — Markdown export (foundation for NotebookLM)
- Reminder scheduling infrastructure

### Changed
- Database schema: added `scheduled_deletions` table for retention policies

---

## [0.3.0] — 2026-04-21 (Phase 3)

### Added
- `/decide <topic>` command — Structured decision view (options, arguments, evidence)
- Contextual retrieval from shared discussion history
- Improved topic clustering logic

---

## [0.2.0] — 2026-04-19 (Phase 2)

### Added
- `/catchup` command — Recent discussion digest
- `/search <keyword>` command — Full-text search across messages + links
- `/topics` command — List active discussion threads
- `/topic <name>` command — Deep dive on specific topic
- New database indexes for query performance

### Changed
- Agent pipeline now supports longer context windows (consolidated summaries for thread depth)

---

## [0.1.0] — 2026-04-19 (Phase 1 — Foundation)

### Added
- Core bot functionality
  - Group message capture (bot.py + db.store_message)
  - Link summarization with Gemini 3 Flash/Pro (BAML + LangGraph)
  - `/start` command (welcome message)
  - URL normalization for dedup (url_normalize.py)

- Database schema (Supabase/Postgres)
  - messages — group message capture
  - link_summaries — extracted & summarized links
  - users — user metadata
  - user_chat_state — per-user per-chat tracking
  - personal_sources — private user notes (future)
  - exports — NotebookLM exports (future)

- Deployment support
  - Polling mode (local dev)
  - Webhook mode (production via Cloud Run)
  - Docker support
  - Configuration management (config.py)

- Content extraction pipeline (5 tools)
  - Tavily API (web pages)
  - PyMuPDF (PDFs)
  - twitterapi.io (tweets)
  - Playwright + AgentQL (YouTube, LinkedIn)

### Documentation
- Created `docs/system-architecture.md` — architecture overview + module breakdown
- Created `docs/code-standards.md` — coding conventions + best practices
- Created `docs/codebase-summary.md` — quick reference guide
- Created `docs/project-overview-pdr.md` — product requirements + overview

---

## Deployment History

| Version | Date | Environment | Notes |
|---------|------|-------------|-------|
| 0.1.0 | 2026-04-19 | Staging | Foundation phase |
| 0.2.0 | 2026-04-19 | Staging | DM commands (catchup, search, topics) |
| 0.3.0 | 2026-04-21 | Staging | Structured intelligence (decide) |
| 0.4.0 | 2026-04-23 | Staging | Extended workflows (remind, export) |
| 0.5.0 | 2026-04-25 | Staging | Rich media + tests |
| (Unreleased) | 2026-04-26 | Staging | Provider abstraction (Phase 7) |

**Production Deployment:** TBD (pending Phase 8 cutover with 24h monitoring per modality)

---

## Breaking Changes

### None in Phase 7
- Default behavior unchanged (`AI_PROVIDER=gemini`)
- All public APIs stable
- BAML clients unchanged
- Test compatibility maintained

---

## Migration Guide

### For Developers Adding New LLM Calls

**Before (Direct SDK import):**
```python
import google.genai
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
response = genai.GenerativeModel("gemini-3-flash").generate_content(prompt)
```

**After (Provider abstraction):**
```python
from src.providers import Feature, get_provider

provider = get_provider(Feature.TEXT)
response = await provider.text_to_text(
    system_prompt="...",
    user_input=prompt,
    generation_config=TextGenerationConfig(max_output_tokens=2000)
)
```

### For Operations (Provider Flipping)

No code changes required. Flip via environment variables:

```bash
# Flip text generation to MiniMax (24h soak recommended)
gcloud run services update murmur --update-env-vars AI_PROVIDER_TEXT=minimax

# Monitor error rates, latency, cost telemetry in Cloud Logging

# Rollback if regression detected (one command)
gcloud run services update murmur --update-env-vars AI_PROVIDER_TEXT=gemini
```

---

## Known Issues & Workarounds

### MiniMax STT Polling Latency
- **Issue:** MiniMax STT is async polling (2s intervals, 30s max) vs Gemini's sync transcription (< 2s)
- **Impact:** Voice transcription takes 2-4s longer on MiniMax
- **Workaround:** Telegram shows "typing..." indicator; UX still acceptable. Swap `AI_PROVIDER_VOICE=gemini` if latency unacceptable.

### BAML Still Gemini-Only
- **Issue:** RouteRequest + SummarizeContent functions in BAML hardcoded to Gemini
- **Impact:** Link summarization ignores `AI_PROVIDER_TEXT` env var (always uses Gemini)
- **Workaround:** Set `AI_PROVIDER_TEXT=minimax` for all non-link text features; BAML migration in Phase 9

### MiniMax No Video Support
- **Issue:** MiniMax does not accept video input; YouTube summaries fail if forced to MiniMax
- **Impact:** `AI_PROVIDER_VOICE=minimax` is valid, but VIDEO must remain Gemini
- **Workaround:** VIDEO is hard-pinned to Gemini (cannot be overridden); no action needed

---

## Future Work

See `docs/development-roadmap.md` for detailed phase planning.

**Immediate (Phase 8 — Provider Cutover):**
- Flip TEXT → MiniMax (24h monitoring)
- Flip IMAGE → MiniMax (24h monitoring)
- Flip VOICE → MiniMax (24h monitoring)
- Validate cost telemetry (40-60% savings target)

**Medium-term (Phase 9 — BAML Deprecation):**
- Migrate RouteRequest + SummarizeContent to provider abstraction
- Enable full MiniMax coverage for link processing

**Long-term (Phase 10 — pgvector + Caching):**
- Semantic search via Supabase pgvector
- Gemini context caching (75% token savings on repeated prompts)
- Expected: 40% overall cost reduction, 50x faster query latency

---

## Contributors & Acknowledgments

- **Phase 1-5:** Initial development, Gemini 3 foundation, rich media support
- **Phase 6-7:** Provider abstraction architecture, MiniMax integration, testing, documentation

---

## License

Apache License 2.0 — see [LICENSE](../LICENSE).
