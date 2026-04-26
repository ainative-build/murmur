# Development Roadmap

**Last Updated:** 2026-04-26  
**Current Phase:** 7 (MiniMax Provider Integration)

## Completed Phases

### Phase 1: Foundation ✅ Complete (2026-04-19)
- ✅ Supabase schema (messages, link_summaries, users, user_chat_state, personal_sources, exports)
- ✅ Group message capture (bot.py + db.store_message)
- ✅ Link summarization with Gemini 3 Flash/Pro
- ✅ `/start` command
- ✅ URL normalization for dedup
- ✅ Config centralization

**Impact:** Core bot functional for silent capture + link summaries in group chats.

---

### Phase 2: Core Usability ✅ Complete
- ✅ `/catchup` — Recent discussion digest
- ✅ `/search <keyword>` — Full-text search
- ✅ `/topics` — Active thread list
- ✅ `/topic <name>` — Deep dive on thread

**Impact:** Users can now interact with bot via DM for intelligent catch-up.

---

### Phase 3: Structured Intelligence ✅ Complete
- ✅ `/decide <topic>` — Structured decision view (options, arguments, evidence)
- ✅ Contextual retrieval from shared discussion history

**Impact:** AI-powered decision support grounded in team context.

---

### Phase 4: Extended Workflows ✅ Complete
- ✅ `/remind` — Configurable reminder digests
- ✅ `/export` — Markdown export (future: NotebookLM integration)

**Impact:** Extended feature set for knowledge curation.

---

### Phase 5: Rich Media ✅ Complete (2026-04-24)
- ✅ Voice transcription (Gemini 3 Flash audio API)
- ✅ File extraction (PDF, DOCX, TXT, MD)
- ✅ YouTube transcript caching
- ✅ Spotify podcast metadata (Web API + oEmbed fallback)
- ✅ TinyFish integration (Grok, X Articles, GitHub)

**Impact:** Bot now handles diverse content types (voice, files, rich media).

---

### Phase 6: Testing & Validation ✅ Complete (2026-04-25)
- ✅ 81 unit + integration tests for provider layer (352 total)
- ✅ Live smoke tests on staging (MiniMax modalities)
- ✅ Provider-specific error handling validated
- ✅ Retry + fallback logic verified

**Impact:** Provider abstraction stable and production-ready.

---

### Phase 7: MiniMax Provider Integration ✅ Complete (2026-04-26)

#### Implementation
- ✅ AI provider abstraction (`src/providers/`)
  - ✅ Base class with retry + fallback
  - ✅ GeminiProvider (Flash/Pro models, audio, vision, files)
  - ✅ MiniMaxProvider (M2.7, audio polling, vision, text extraction)
  - ✅ Factory with env-driven switching
  - ✅ Structured JSON telemetry (`provider_usage` log lines)

- ✅ Prompt module extraction (`src/ai/prompts/`)
  - ✅ catchup, topics, topic_detail, decide, draft, reminder
  - ✅ Composable builders (system_prompt, user_prompt)

- ✅ Orchestration refactor
  - ✅ summarizer.py: 401 → 175 LOC (thin delegation layer)
  - ✅ voice_transcriber.py: delegates to provider
  - ✅ bot._analyze_image: delegates to provider

- ✅ Environment configuration
  - ✅ `AI_PROVIDER` global default
  - ✅ `AI_PROVIDER_TEXT|IMAGE|FILE|VOICE` per-modality overrides
  - ✅ `MINIMAX_API_KEY` and `MINIMAX_BASE_URL` support

#### Modality Status
| Feature | Default | Alt Provider | Status |
|---------|---------|--------------|--------|
| TEXT | Gemini | MiniMax ✅ | Configurable |
| IMAGE | Gemini | MiniMax ✅ | Configurable |
| FILE | Gemini | MiniMax (≤ TBD) | Gemini-pinned (BAML) |
| VOICE | Gemini | MiniMax ✅ | Configurable |
| VIDEO | Gemini | — | Pinned (no MiniMax support) |
| ROUTING | Gemini | — | Pinned (BAML only) |

**Impact:** 30-60% estimated cost savings on text+image+voice (target: TEXT first). No code rebuild for provider flips — env-only. All callsites changed from direct SDK calls to `get_provider(Feature).method()`.

---

## Upcoming Work

### Phase 8: Provider Cutover (Planned)
- Flip `AI_PROVIDER_TEXT` → minimax + 24h monitoring
- Flip `AI_PROVIDER_IMAGE` → minimax + 24h monitoring
- Flip `AI_PROVIDER_VOICE` → minimax + 24h monitoring
- Validate cost telemetry (40-60% reduction target)
- Document cost/latency observations
- Rollback strategy: single env var flip back to gemini if regression

**Success Criteria:** All four modalities stable, no error-rate regression, cost reduction ≥30%.

---

### Phase 9: BAML Deprecation (Planned, Out of Scope)
- Migrate `RouteRequest` (link type classification) to provider abstraction
- Migrate `SummarizeContent` (link summarization) to provider abstraction
- Retire BAML clients.baml dependency
- Enable full MiniMax coverage for link processing

**Impact:** Unified provider abstraction across all LLM calls; further cost savings on link summaries.

---

### Phase 10: pgvector + Context Caching (Planned, Out of Scope)
- Add Supabase pgvector extension
- Embed all messages + summaries via Gemini embeddings
- Semantic search for `/search` and `/decide` (retrieve top-30 relevant instead of brute-force 200+)
- Gemini context caching for system prompts (75% token savings on cached portion)
- Expected impact: 40% cost reduction, 50x faster query latency

---

## Metrics & Health

| Metric | Target | Current Status | Notes |
|--------|--------|---|--------|
| Test Coverage | > 90% | 352 tests (263 existing + 81 new) | Phase 6 complete |
| Provider Error Rate | < 0.1% | TBD (post-cutover) | Monitoring Phase 8 |
| Message Capture Latency | < 500ms | ~100ms | Consistent |
| Link Summary Latency | 3-10s | 3-10s | Tool-dependent |
| Cost Ratio (MiniMax/Gemini) | 0.4-0.6 | Estimated (post-cutover) | Text: 40-60% savings target |
| Uptime | > 99.9% | Cloud Run SLA | Both providers included |

---

## Dependencies & Blockers

### Runtime Dependencies
- `google-genai >=0.1.0` — Gemini provider
- `minimax-api >=0.2.0` — MiniMax provider
- All other Phase 1-6 dependencies unchanged

### External Integrations
- Telegram API (unchanged)
- Supabase (unchanged)
- Google Gemini (unchanged)
- MiniMax API (Phase 7+)
- All content extraction tools (unchanged)

### Known Constraints (Phase 7)
1. **BAML still pinned to Gemini** — Link routing/summarization not yet migrated. BAML deprecation tracked separately (Phase 9).
2. **MiniMax has no video input** — YouTube summaries remain Gemini-only (hard constraint).
3. **MiniMax STT is polling-based** — Adds ~2-4s latency vs Gemini's sync API. Telegram already shows "typing..." indicator; acceptable UX.

---

## Documentation Status

- ✅ `docs/system-architecture.md` — AI provider layer documented + modality matrix
- ✅ `docs/code-standards.md` — Provider integration rule added
- ✅ `docs/codebase-summary.md` — Provider + prompts modules mapped
- ✅ `README.md` — Tech stack + env vars updated
- ✅ `docs/development-roadmap.md` — This file
- ⏳ `docs/project-changelog.md` — See below

---

## Glossary

| Term | Definition |
|------|-----------|
| **Provider Abstraction** | `src/providers/` interface enabling multi-LLM routing |
| **Feature** | Modality enum (TEXT, IMAGE, FILE, VOICE, VIDEO, ROUTING) |
| **Env Precedence** | `AI_PROVIDER_<FEATURE>` > `AI_PROVIDER` > `gemini` |
| **Cutover** | Operational flip of env vars to switch providers in production (no rebuild) |
| **Telemetry** | Structured JSON log lines tagged `event: provider_usage` for cost tracking |
| **Pinned** | Hard constraint — single provider required (e.g., VIDEO → Gemini only) |
| **BAML** | Boundary ML framework for structured outputs (currently Gemini-only) |
