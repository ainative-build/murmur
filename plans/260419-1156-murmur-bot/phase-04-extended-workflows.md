# Phase 4: Extended Workflows

## Context
- [Plan Overview](plan.md)
- Depends on: [Phase 1](phase-01-foundation.md) (Supabase + bot), [Phase 2](phase-02-core-usability.md) (memory model)
- [notebooklm-py](https://github.com/teng-lin/notebooklm-py) — unofficial Python SDK

## Overview
- **Priority:** Medium — extends the core, not blocking it
- **Status:** Completed
- **Scope:** Reminders, NotebookLM export

## Key Insights
- Reminders and NotebookLM export **plug into the same stored memory model** — not separate side systems
- Reminders query `messages` + `users` (same tables as /catchup)
- Export queries `messages` + `link_summaries` (same tables as /topics)
- No new data models needed — these are output channels on existing data
- **Topic identity caveat**: topic names are LLM-derived per /topics run, not persisted. Export dedup uses `content_hash` as the stable key, not topic name. If topic names drift between runs, exports may create near-duplicate entries. Acceptable for v1; persist topic IDs if it becomes noisy.

## Requirements

### Functional — Reminders
- `/remind <off|daily|weekly>` — configure reminder frequency
- Proactive DM reminders: new message count, stale topics, activity digest
- Reminder content derived from same data as /catchup (shared memory model)
- Respect user timezone

### Functional — NotebookLM Export
- Daily cron: export new/updated topics as documents to NotebookLM
- Each topic = one source document (title, messages, links, summaries)
- `/export` command — manual trigger for immediate export
- `/kb` command — link to NotebookLM notebook for team Q&A
- Deduplication: don't re-upload unchanged topics

### Non-Functional
- Reminders via **Cloud Scheduler → HTTP endpoint** on bot (preferred for production reliability; APScheduler as local-dev fallback only)
- Export format: structured markdown per topic
- Fallback if notebooklm-py fails: markdown export to Google Drive

## Architecture

```
Reminders (scheduled, plugs into existing memory)
  ├── Query messages since user's last_catchup_at  ← same as /catchup
  ├── Count new activity per topic
  ├── Check stale topics (>3 days no new messages)
  └── DM users per their frequency preference

NotebookLM Export (scheduled or /export, plugs into existing memory)
  ├── Query messages + link_summaries by topic  ← same as /topics
  ├── Format as structured markdown per topic
  ├── Hash content for dedup
  └── Upload via notebooklm-py (fallback: Google Drive)
```

## Related Code Files

### Files to modify:
- `bot.py` — add /remind, /export, /kb commands, scheduler setup
- `commands.py` — add handler functions
- `db.py` — add reminder query helpers (reuse existing catchup queries)
- `summarizer.py` — add reminder digest prompt

### Files to create:
- `reminders.py` — scheduled reminder logic
- `exporter.py` — topic document generation + NotebookLM upload
- `export_formatter.py` — markdown document builder per topic

## Implementation Steps

### Reminders

1. **Modify `bot.py`** — Add:
   - `CommandHandler("remind", remind_handler)`
   - HTTP endpoint `POST /api/check-reminders` — called by Cloud Scheduler
   - (APScheduler as local-dev fallback only; production uses Cloud Scheduler)

2. **Extend `commands.py`**:
   - `remind_handler` — parse args (off/daily/weekly) → update user preferences in Supabase

3. **Create `reminders.py`** — Scheduled logic:
   - `check_and_send_reminders()` — called by scheduler:
     - For each user with reminders enabled and due:
       - Reuse `db.get_messages_since(chat_id, user.last_catchup_at)` — same query as /catchup
       - Count new messages, identify stale topics
       - Generate brief digest via `summarizer.generate_reminder_digest()`
       - Send DM: "X new messages across Y topics. /catchup to review. Stale: {topics}"
   - Timezone-aware scheduling using user's IANA timezone from `users.timezone` (default UTC, user-configurable via /remind)

4. **Extend `summarizer.py`**:
   - `generate_reminder_digest(messages, stale_topics)` — brief summary for reminder DM

### NotebookLM Export

5. **Create `export_formatter.py`** — Build topic documents:
   - `format_topic_document(topic, messages, links)` → markdown string:
     ```markdown
     # Topic: {topic}
     ## Summary
     {AI-generated topic summary}
     ## Discussion Timeline
     - [2026-04-15 user1]: message...
     ## Key Links
     - {url}: {summary}
     ## Status: Active / Decided / Stale
     ```
   - Hash content for dedup comparison

6. **Create `exporter.py`** — Export orchestrator:
   - `export_topics(since_last=True)`:
     - Reuse topic detection from summarizer (same as /topics)
     - Format each topic via export_formatter
     - Check content_hash in `exports` table for dedup
     - Upload to NotebookLM via notebooklm-py
   - `upload_to_notebooklm(notebook_id, title, content)` — create/update source
   - `export_to_gdrive(folder_id, title, content)` — fallback
   - `export_to_markdown(output_dir, title, content)` — local fallback

7. **Modify `bot.py`** — Add:
   - `CommandHandler("export", export_handler)` — trigger manual export
   - `CommandHandler("kb", kb_handler)` — reply with NotebookLM notebook link
   - Add daily export job to scheduler

8. **Environment variables**:
   - `NOTEBOOKLM_NOTEBOOK_ID` — target notebook
   - `GOOGLE_CREDENTIALS_PATH` — for notebooklm-py auth
   - `GDRIVE_FOLDER_ID` — fallback folder

9. **Test**:
   - `/remind daily` → sets preference, reminder fires at scheduled time
   - Reminder uses same data as /catchup (no parallel data path)
   - `/export` → topics appear in NotebookLM
   - Re-export unchanged topic → skipped (dedup)
   - notebooklm-py failure → fallback to markdown/gdrive

## Todo

### Reminders
- [x] Add /remind command to bot.py + commands.py
- [x] Create reminders.py — scheduled check using existing catchup queries
- [x] Add APScheduler to bot startup
- [x] Add reminder digest prompt to summarizer.py
- [x] Test timezone-aware reminder delivery

### NotebookLM Export
- [x] Install and test notebooklm-py locally
- [x] Create export_formatter.py — topic document builder
- [x] Create exporter.py — orchestrator with notebooklm-py + fallbacks
- [x] Add /export and /kb commands
- [x] Add daily export to scheduler
- [x] Test deduplication
- [x] Test fallback paths (gdrive, local markdown)

## Acceptance Criteria (Testable)
- [x] `/remind daily` → user's `reminder_frequency` set to 'daily' in Supabase
- [x] Cloud Scheduler fires `POST /api/check-reminders` → bot DMs users with new message count + stale topics
- [x] Reminder content covers same messages as `/catchup` would (same query path)
- [x] User in UTC+7 with `reminder_time='09:00'` receives reminder at ~09:00 ICT, not UTC
- [x] `/export` → each topic becomes a source document in NotebookLM with title, timeline, links
- [x] Run `/export` twice with no new messages → second run creates 0 new `exports` rows (content_hash dedup)
- [x] notebooklm-py failure → export falls back to Google Drive markdown files; `exports` row still created with `export_target='gdrive'`
- [x] `/kb` → replies with NotebookLM notebook URL

## Risk Assessment
| Risk | Impact | Mitigation |
|------|--------|------------|
| Cloud Run scales to zero, kills in-process scheduler | No reminders | Use Cloud Scheduler (primary); APScheduler only for local dev |
| notebooklm-py breaks/gets blocked | No export | Fallback: Google Drive markdown files |
| NotebookLM rate limits | Throttled exports | Batch 1x/day, exponential backoff |
| Google auth complexity | Setup friction | Document clearly, use service account |

## Security
- Google credentials via service account, not personal auth
- Exported content = group-level only (no personal sources exported)
- NotebookLM notebook shared only with team
- Reminder content respects same privacy boundary as /catchup
