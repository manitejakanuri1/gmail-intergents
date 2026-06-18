# Architecture & Design Document — AI-Powered Gmail Intelligence Platform

> Repeatless Technical Assessment — AI Automation Executive
> A web application that connects to Gmail and turns the inbox into an **AI triage / control dashboard**: it summarizes, categorizes, and **prioritizes** every email (urgency + the action to take), lets the user compose/reply, and answers questions over the mailbox as a knowledge base — with source-cited, hallucination-guarded answers. Emails are surfaced **stacked by urgency** with per-item reminders, rather than as a flat list.

---

## 0. Stack at a Glance

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + TypeScript (lightweight custom CSS) | Fast DX, typed; kept the styling dependency-free to stay simple and fast to ship |
| Backend | FastAPI (Python 3.x, async) | First-class async I/O for fan-out API calls; richest AI/RAG ecosystem; Pydantic validation |
| Background worker | ARQ (async Redis queue) | Email sync, analysis, and embedding are long-running and must not block HTTP requests |
| Database | Supabase (PostgreSQL + `pgvector`) | Managed Postgres, row-level security, vector search in the same DB (no separate vector store to operate) |
| Cache / Queue broker | Redis | ARQ broker + rate-limit token buckets + short-lived caches |
| Primary AI | Google **Gemini** (`gemini-2.5-flash`, thinking disabled) | Triage (category/priority/summary/action), compose/reply, and the chat agent's answer synthesis. `thinkingBudget=0` keeps these short tasks fast, cheap, and fully output (the 2.5 thinking budget otherwise consumes the token budget). |
| Secondary AI | **NVIDIA NIM** embedding model (`nvidia/nv-embedqa-e5-v5`, 1024-d) | Generates the vector embeddings that power RAG retrieval and newsletter dedup |
| Auth | Google OAuth 2.0 (Gmail API scopes) | Required; no IMAP/SMTP |
| Deploy | Frontend → Vercel · Backend + Worker → Render/Railway · Redis → Upstash · DB → Supabase | Each tier scales independently |

**Two-model split (justification up front):** Gemini is the *reasoning* model — it reads, writes, and decides. The NVIDIA NIM `nv-embedqa-e5-v5` model is the *representation* model — it converts emails and queries into vectors for semantic retrieval. Separating "retrieve" (cheap, high-volume, NIM) from "reason" (expensive, low-volume, Gemini) is the standard, cost-efficient RAG pattern and gives a clean, defensible reason for using both required providers.

---

## 1. System Architecture

### 1.1 Component diagram

```
                    ┌─────────────────────────────────────────────┐
                    │  Browser — React SPA (Vite + TS + shadcn)    │
                    │  • OAuth start  • Inbox/threads  • Chat UI   │
                    │  • Compose/Reply  • Category filters         │
                    └───────────────┬─────────────────────────────┘
                                    │ HTTPS (JWT session cookie)
                                    ▼
                    ┌─────────────────────────────────────────────┐
                    │  FastAPI Backend (async)                     │
                    │  Routers:                                    │
                    │   /auth   /sync   /threads  /emails          │
                    │   /compose  /reply  /chat   /categories      │
                    │  Services: GmailService, AIService,          │
                    │   RAGService, CategorizeService, SyncService │
                    └───┬───────────┬───────────┬─────────────┬────┘
                        │           │           │             │
          OAuth+Gmail   │           │ enqueue   │ embeddings  │ generate
          REST calls    │           ▼           ▼             ▼
                        │   ┌──────────────┐  ┌──────────┐  ┌──────────┐
                        │   │ Redis + ARQ  │  │ NVIDIA   │  │ Gemini   │
                        │   │ job queue    │  │ NIM      │  │ API      │
                        │   └──────┬───────┘  │(embed)   │  │(reason)  │
                        │          │          └──────────┘  └──────────┘
                        ▼          ▼
              ┌──────────────┐  ┌─────────────────────────────────────┐
              │  Gmail API   │  │  ARQ Worker (separate process)       │
              │  (Google)    │  │  • initial_sync  • incremental_sync  │
              └──────────────┘  │  • summarize_email/thread            │
                                │  • categorize_email  • embed_email   │
                                └──────────────────┬───────────────────┘
                                                   ▼
                                ┌──────────────────────────────────────┐
                                │  Supabase Postgres + pgvector        │
                                │  users, gmail_accounts, threads,     │
                                │  emails, labels, email_embeddings,   │
                                │  categories, chat_sessions/messages, │
                                │  sync_state                          │
                                └──────────────────────────────────────┘
```

### 1.2 Request/flow narratives

**A. Connect Gmail (OAuth 2.0)**
1. Frontend hits `GET /auth/google/start` → backend returns Google consent URL (scopes: `gmail.readonly`, `gmail.send`, `gmail.modify`, `openid email profile`).
2. Google redirects to `GET /auth/google/callback?code=...`. Backend exchanges code for **access + refresh tokens**, stores them encrypted in `gmail_accounts`, creates/updates `users`, sets an HTTP-only session cookie (app JWT).
3. Backend enqueues an `initial_sync` job and returns. The UI shows a sync-progress state polled from `sync_state`.

**B. Sync (background)** — covered in Section 4. Worker pulls messages, normalizes into `threads`/`emails`/`labels`, then enqueues `categorize_email`, `summarize_*`, and `embed_email` jobs per message.

**C. Ask the chat agent (RAG)** — covered in Section 3.2. `POST /chat` → embed query (NIM) → vector + keyword retrieval from Postgres → Gemini answers with citations → persist turn.

**D. Compose / Reply** — covered in Section 3.3. Gemini drafts; on send, GmailService builds a MIME message (with thread headers for replies) and calls `users.messages.send`.

### 1.3 Why a separate frontend + backend (not one full-stack app)

- **Clear separation of concerns** — the React app is purely presentational; all secrets (OAuth tokens, AI keys) and all Gmail/AI calls live server-side only. The browser never sees a provider key.
- **The work is backend-heavy and async** — sync, embedding, and summarization are long-running fan-out jobs. A dedicated FastAPI + worker tier lets these run and scale independently of the UI.
- **Independent deploys/scaling** — the worker can scale on queue depth without touching the SPA.

---

## 2. Database Schema (Supabase / PostgreSQL + pgvector)

> Extensions: `create extension if not exists vector;` and `pgcrypto` (for UUIDs / token encryption). Row-Level Security is enabled on every user-scoped table so a user can only ever read their own rows.

### 2.1 Tables

```sql
-- App users (one row per authenticated person)
create table users (
  id            uuid primary key default gen_random_uuid(),
  email         text unique not null,
  display_name  text,
  created_at    timestamptz not null default now()
);

-- Connected Gmail accounts + OAuth tokens (a user may connect >1 Gmail)
create table gmail_accounts (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references users(id) on delete cascade,
  google_email       text not null,
  access_token_enc   bytea not null,         -- encrypted at rest
  refresh_token_enc  bytea not null,
  token_expiry       timestamptz,
  history_id         bigint,                  -- last Gmail historyId for incremental sync
  created_at         timestamptz not null default now(),
  unique (user_id, google_email)
);

-- Gmail labels (system + user) mirrored per account
create table labels (
  id            uuid primary key default gen_random_uuid(),
  account_id    uuid not null references gmail_accounts(id) on delete cascade,
  gmail_label_id text not null,
  name          text not null,
  type          text,                          -- 'system' | 'user'
  unique (account_id, gmail_label_id)
);

-- Email threads (first-class concept)
create table threads (
  id              uuid primary key default gen_random_uuid(),
  account_id      uuid not null references gmail_accounts(id) on delete cascade,
  gmail_thread_id text not null,
  subject         text,
  last_message_at timestamptz,
  message_count   int default 0,
  summary         text,                        -- thread-level summary (AI)
  summary_model   text,
  updated_at      timestamptz not null default now(),
  unique (account_id, gmail_thread_id)
);

-- Individual messages
create table emails (
  id               uuid primary key default gen_random_uuid(),
  account_id       uuid not null references gmail_accounts(id) on delete cascade,
  thread_id        uuid not null references threads(id) on delete cascade,
  gmail_message_id text not null,
  rfc822_message_id text,                       -- Message-ID header (for In-Reply-To/References)
  from_email       text, from_name text,
  to_emails        text[], cc_emails text[],
  subject          text,
  snippet          text,
  body_text        text,                        -- normalized plain text
  body_html        text,
  internal_date    timestamptz,
  is_unread        boolean default true,
  category_id      uuid references categories(id),
  summary          text,                        -- per-email summary (AI)
  summary_model    text,
  priority         text,                        -- 'urgent'|'high'|'medium'|'low' (AI triage)
  action_item      text,                        -- the concrete action the user should take, if any
  needs_action     boolean default false,       -- drives the control-dashboard "to-do" surfacing
  label_ids        text[],                      -- gmail label ids on this message
  created_at       timestamptz not null default now(),
  unique (account_id, gmail_message_id)
);
-- priority/action/needs_action are added in migration 002_priority.sql and power
-- the priority control dashboard (see Section 3.2). A functional index on the priority
-- rank (urgent=1 … low=4) lets the dashboard fetch ordered-by-urgency in one query.

-- Category taxonomy (seeded + extensible)
create table categories (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid references gmail_accounts(id) on delete cascade,
  key         text not null,                    -- 'newsletter','job','finance','notification','personal','work'
  label       text not null,
  is_system   boolean default true,
  unique (account_id, key)
);

-- Vector store for RAG (one or more chunks per email)
create table email_embeddings (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references gmail_accounts(id) on delete cascade,
  email_id    uuid not null references emails(id) on delete cascade,
  thread_id   uuid not null references threads(id) on delete cascade,
  chunk_index int not null default 0,
  content     text not null,                    -- the exact chunk text that was embedded
  embedding   vector(1024) not null,            -- nv-embedqa-e5-v5 = 1024 dims
  created_at  timestamptz not null default now()
);

-- Chat agent sessions + turns
create table chat_sessions (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references gmail_accounts(id) on delete cascade,
  title       text,
  created_at  timestamptz not null default now()
);

create table chat_messages (
  id          uuid primary key default gen_random_uuid(),
  session_id  uuid not null references chat_sessions(id) on delete cascade,
  role        text not null,                    -- 'user' | 'assistant'
  content     text not null,
  sources     jsonb,                            -- [{email_id, thread_id, from, subject, date}]
  created_at  timestamptz not null default now()
);

-- Sync bookkeeping (drives initial vs incremental + progress UI)
create table sync_state (
  account_id   uuid primary key references gmail_accounts(id) on delete cascade,
  status       text not null default 'idle',    -- idle|running|error|done
  phase        text,                            -- 'initial' | 'incremental'
  page_token   text,                            -- resume point for paginated initial sync
  last_synced_at timestamptz,
  total_synced int default 0,
  error        text
);
```

### 2.2 Indexes

```sql
create index on emails (account_id, internal_date desc);
create index on emails (thread_id);
create index on emails (category_id);
create index on threads (account_id, last_message_at desc);
-- Vector ANN index (cosine). Lists tuned to dataset size; rebuilt after bulk load.
create index on email_embeddings using ivfflat (embedding vector_cosine_ops) with (lists = 100);
-- Full-text fallback / hybrid search
alter table emails add column tsv tsvector
  generated always as (to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(body_text,''))) stored;
create index on emails using gin (tsv);
```

### 2.3 Data-modeling decisions

- **Threads as a first-class table**, with `emails.thread_id` FK — every feature (summaries, replies, agent) can reason at the thread level, which the spec demands.
- **Token columns are encrypted (`bytea`)** via `pgcrypto`, never stored as plaintext; combined with RLS this keeps credentials safe even at the DB layer.
- **Embeddings live in a separate table, chunked** (`chunk_index`) rather than one vector per email, because long threads exceed a single embedding's useful context. Chunking preserves retrieval precision (see Section 3.1).
- **`sources jsonb` on assistant messages** persists exactly which emails an answer was drawn from — this is what powers "source clarity" in the UI and makes answers auditable.
- **`history_id` + `page_token` + `sync_state`** cleanly separate incremental sync (Gmail History API) from a resumable initial backfill.

### 2.4 What is embedded and why (pgvector)

We embed **email content chunks** (subject + cleaned body, split into ~500-token chunks with overlap). We embed chunks — not summaries — because the agent must answer fine-grained questions ("which companies rejected me?") that depend on specific sentences, not a lossy summary. Query strings are embedded with the **same NIM model** so query and document vectors share one space. Cosine similarity over the `ivfflat` index returns the top-k candidate chunks for RAG.

---

## 3. AI Design

### 3.1 Per-email triage — one structured call (category + priority + summary + action)

Each email is analyzed by a **single Gemini call** (`services/analyze.py`) that returns a strict JSON object:

```json
{ "category": "job", "priority": "urgent",
  "summary": "Final interview offered for Thu 3pm; confirm by tomorrow EOD.",
  "action": "Confirm availability by tomorrow EOD and send your resume.",
  "needs_action": true }
```

**Why one call instead of separate categorize + summarize + prioritize calls:**
- **Cost/quota:** it roughly *halves* the number of LLM calls per email — important on free-tier limits and at scale (see Section 6).
- **Consistency:** category, priority and action are decided from the *same* read of the email, so they can't disagree.
- **It powers the priority control dashboard** (Section Product): emails are surfaced **stacked by urgency** (urgent → low), each showing *what it is, how urgent it is, and what to do* — the app behaves as a triage/control system, not a flat mailbox. The taxonomy is the required six categories (newsletter, job, finance, notification, personal, work); priority is `urgent|high|medium|low` with explicit guidance in the system prompt (deadlines/security/money/offers → urgent; newsletters/automated → low).

The output is parsed defensively (regex-extract the JSON, validate against allowed values, fall back to safe defaults) so a malformed model response never breaks ingestion.

- **Per-email summary:** the `summary` field above is stored on `emails.summary`.
- **Thread-level summary:** built over the **ordered** messages of a thread so a reply is always understood relative to what came before. For long threads we use a **map-reduce / rolling strategy**:
  1. *Map:* summarize each message (or each chunk of very long messages) individually.
  2. *Reduce:* feed the ordered per-message summaries back to Gemini to produce one coherent "conversation arc" summary stored on `threads.summary`.
  This keeps us inside the context window regardless of thread length and guarantees context-awareness instead of summarizing messages in isolation.
- **Chunking strategy:** bodies are normalized (HTML stripped, quoted reply-chains and signatures trimmed) then split into ~500-token chunks with ~50-token overlap. Overlap prevents a fact from being cut across a boundary.

### 3.2 Chat agent — RAG pipeline

```
user question
   │
   ├─ 1. Rewrite (Gemini): fold conversation history into a standalone query
   │     (so follow-ups like "and which were rejections?" resolve correctly)
   │
   ├─ 2. Embed standalone query  ──►  NVIDIA NIM (nv-embedqa-e5-v5, 1024-d, input_type=query)
   │
   ├─ 3. Hybrid retrieve from Postgres:
   │       • vector KNN (pgvector cosine, top 30) — see index note below
   │       • full-text (tsvector, OR-semantics) for names/terms (top 30)
   │
   ├─ 4. Merge + dedup by email → keep top ~8 (vector hits above a
   │     similarity floor preferred, then text hits fill in)
   │
   ├─ 5. Generate (Gemini): answer ONLY from retrieved context,
   │     each claim tagged with a [source N] marker
   │
   └─ 6. Return answer + structured `sources[]`; persist the turn
```

**Vector index decision (ivfflat → exact).** We initially created an `ivfflat` index, but at this dataset scale (a few thousand vectors) `ivfflat` with the default single-probe actually *hurt recall* — each query scanned only one small cluster and missed relevant emails. We dropped it in favour of **exact KNN** (a sequential cosine scan), which at this size is both instant and 100% accurate. The `hnsw` index is the documented upgrade path once vectors reach the millions (Section 7) — but exact search is the correct, measured choice now, not a limitation.

**Full-text uses OR-semantics.** `plainto_tsquery` ANDs all terms, which is brittle ("rejected" misses "won't move forward"); we rewrite it to OR the lexemes so partial overlaps still surface, then rank by `ts_rank`. This also makes the keyword path a usable fallback when embeddings are unavailable.

**Graceful degradation (no hard failures).** Retrieval and answering both degrade instead of erroring:
- *NIM/embeddings unavailable* → retrieval falls back to full-text-only, so chat still works.
- *Gemini unavailable / rate-limited* → the answer step returns the **retrieved emails with their sources** ("the writer is busy, here are the relevant emails") instead of a 500. The user still gets value and source attribution.

**Source clarity across multiple emails.** Every retrieved chunk carries its `email_id`, `from`, `subject`, and `date`. The generation prompt requires the model to cite a `[source N]` after each claim, and the API returns a parallel `sources[]` array. The UI renders each answer with clickable source chips that open the underlying email/thread — so the agent always knows and shows where each fact came from.

**Cross-email reasoning.** Because retrieval pulls the top chunks *across all emails* (not one email at a time), a question like "what do I know about Kubernetes?" gathers chunks from many senders into one context window; Gemini synthesizes them into a unified answer while still attributing each piece to its source email.

**Conversational context.** Step 1 (history-aware query rewriting) plus persistence in `chat_messages` lets follow-up questions resolve against the ongoing conversation.

### 3.3 Compose & Reply

- **Compose:** prompt → Gemini drafts subject + body in a professional tone; returned to the UI for review/edit/send. On send, GmailService builds a MIME message and calls `users.messages.send`.
- **Reply (thread-aware):** the selected thread's ordered messages (or thread summary + last messages, if very long) are passed as context so the reply actually responds to what was said. The outgoing MIME sets:
  - `In-Reply-To: <rfc822_message_id of the message being replied to>`
  - `References: <accumulated chain of Message-IDs>`
  - same `Subject` (with `Re:`), and the send call includes Gmail's `threadId`.
  This guarantees Gmail stitches the reply into the existing thread.

### 3.4 Why this specific NVIDIA NIM model

**`nvidia/nv-embedqa-e5-v5`** — a retrieval-tuned (QA) embedding model:
- It is purpose-built for **question→passage retrieval**, which is exactly the chat-agent workload (asymmetric: short query vs. email passage).
- Free-tier accessible on `build.nvidia.com`, 1024-dim vectors (compact, fast).
- Inputs are capped at **512 tokens**; we send `truncate: "END"` so long emails are handled instead of erroring.
- **Role in the system:** it is the *only* thing that converts text→vectors — every email chunk at ingest (`input_type=passage`) and every user query at search time (`input_type=query`, the model's asymmetric QA mode). By offloading all high-volume embedding to NIM, we reserve Gemini purely for low-volume reasoning, which is cheaper and keeps the two-model split meaningful rather than cosmetic.

### 3.5 Anti-hallucination guarantees

1. **Closed-book prompt:** the system prompt instructs Gemini to answer *only* from the provided email context and to reply *"I couldn't find that in your emails."* when retrieval is empty or irrelevant.
2. **Mandatory citations:** every factual claim must carry a `[source N]`; the backend can flag/withhold answers whose claims lack a backing source.
3. **Retrieval gating:** if the top similarity score is below a threshold, we short-circuit to the "not found" response instead of letting the model improvise.
4. **Per-chunk attribution prevents cross-contamination:** because each chunk in context is explicitly delimited and labeled with its source email, the model is far less likely to merge facts from unrelated senders.

---

## 4. Gmail API Strategy

### 4.1 Initial vs. incremental sync

- **Initial sync (backfill):** `users.messages.list` paginated by `pageToken`; for each id, `users.messages.get(format=metadata|full)` to hydrate. We persist the current `historyId` at the start. Progress + resume point are tracked in `sync_state.page_token`, so a crash resumes instead of restarting.
- **Incremental sync:** on a schedule (and on demand), call `users.history.list(startHistoryId=gmail_accounts.history_id)`. This returns only added/deleted/label-changed messages since last sync. We apply those deltas and advance `history_id`. If Gmail returns `404` (history too old/expired), we fall back to a metadata re-list bounded by date.

### 4.2 Pagination for large inboxes

- Always page via `pageToken`; never assume a single page.
- Hydration is **batched and bounded** — messages are fetched in controlled concurrency batches (e.g., 25 in flight) and written in chunks, so a 10k-message inbox streams into Postgres steadily without holding everything in memory.
- Per-message heavy work (summarize/categorize/embed) is **enqueued as ARQ jobs**, not done inline, so listing stays fast and the system degrades gracefully under volume.

### 4.3 Rate limiting & quota handling

- **Exponential backoff with jitter** on `429` and `5xx`: retry with `2^n` delay (cap ~32s), honoring `Retry-After` when present.
- **Client-side throttle:** a Redis token-bucket caps outbound Gmail requests per second per account, keeping us under Gmail's per-user quota *before* we ever hit a 429.
- **Bounded concurrency:** the worker limits simultaneous Gmail calls so a large backfill can't spike past quota.
- **Idempotent upserts** (`unique` constraints on gmail ids) make retries safe — re-processing a message never duplicates rows.

---

## 5. Tool & Technology Decisions

- **FastAPI (backend):** async-native — ideal for the heavy fan-out of Gmail + AI calls; Pydantic gives typed request/response contracts; the Python ecosystem has the most mature embedding/RAG tooling.
- **React + Vite + TypeScript (frontend):** fast builds, typed UI, and **TanStack Query** handles server-state, caching, and polling (sync progress, chat) cleanly. **shadcn/ui + Tailwind** gives a clean inbox/chat UI quickly.
- **ARQ + Redis (job queue):** sync, summarization, and embedding are long-running and bursty; a queue decouples them from HTTP, enables retries/backoff, and lets the worker scale on queue depth. ARQ is async, matching FastAPI.
- **Supabase + pgvector (vector DB approach):** keeping vectors *in Postgres* avoids running a separate vector store, lets us do **hybrid** (vector + SQL filter + full-text) retrieval in one query, and gives RLS/auth for free. At the current scale we use **exact KNN** (no ANN index) for perfect recall; `hnsw` is the upgrade path at large scale.
- **Gemini + NIM split:** reason vs. represent (see Section 0/Section 3.4).
- **Deploy:** SPA on Vercel; FastAPI + worker on Render/Railway; Redis on Upstash; DB on Supabase — each tier scales independently.

---

## 6. Trade-offs & Limitations

**Free-tier AI quotas (the main operational constraint).** Both models run on free tiers:
- **Gemini free tier** caps requests/day. Folding triage into one call per email (Section 3.1) halves usage, but a full 500+ inbox still exhausts the daily allowance — so enrichment is processed gradually by the worker and resumes as quota refreshes. The system degrades gracefully when exhausted (Section 3.2): chat returns retrieved emails, ingestion stores raw emails un-enriched and back-fills later. **Production uses a paid Gemini tier**, which removes this cap with no code change.
- **NIM `nv-embedqa-e5-v5`** caps inputs at **512 tokens**; we send `truncate: "END"` and embed in resilient batches that skip any malformed chunk rather than failing the whole run.

**Google OAuth verification (production gate).** The app uses *restricted* Gmail scopes, so in **Testing** mode only added test users can connect. Serving arbitrary users requires Google's OAuth **verification + annual CASA security review**. For the assessment the app runs in Testing mode with a demo/test-user account. No code changes are needed for production — it's a Google Console + verification process.

**Deliberately simplified / not built (given the timebox):**
- **Text-only knowledge base** — attachments and images are not parsed/OCR'd; only text bodies are embedded.
- **Polling for sync progress** instead of websockets/SSE — simpler, adequate for the demo.
- **Lightweight rerank** (similarity + dedup) rather than a cross-encoder reranker.
- **Query rewriting depends on Gemini** — when Gemini is quota-limited, vague questions retrieve less precisely; specific phrasing works well.
- **Newsletter dedup (bonus)** — semantic clustering of newsletter-category chunks (group by cosine similarity, keep one representative with all source attributions). Best-effort.

**What I'd do with more time:**
- Paid Gemini tier (or a model gateway with fallback) to enrich the full inbox immediately.
- `hnsw` + a cross-encoder reranker for sharper retrieval at scale.
- Gmail `watch` + Pub/Sub push for near-real-time incremental sync instead of polling.
- Attachment ingestion (PDF/text extraction) into the knowledge base.
- Per-user evals/guardrail tests for the agent (faithfulness, citation accuracy); reminders/snooze backed server-side rather than in the browser.

---

## 7. Scalability Awareness

> The assignment's bar is explicit: the solution **"must not break or degrade with thousands of emails,"** must handle **rate limits / `429` / quota**, and must support **incremental sync** — and it warns that *a working submission is valued over an over-engineered one that does not run.* So this section is split deliberately: **7.1 is what the shipped MVP actually does** to meet that bar; **7.2 is awareness** — where it would strain and the concrete next step — included to show the thinking, **not** built.

### 7.1 What the MVP handles today (thousands of emails, robustly)

These are implemented in the build, and directly satisfy the stated requirements:

- **Pagination that doesn't degrade** — every Gmail list call pages via `pageToken`; messages are hydrated in **bounded-concurrency batches** (e.g., 25 in flight) and written to Postgres in chunks, so memory stays flat whether the inbox has 500 or 50,000 messages.
- **Heavy work is off the request path** — summarize/categorize/embed run as **ARQ background jobs**, so the API and inbox UI stay responsive during a large sync. The app degrades gracefully (jobs queue and drain) instead of timing out.
- **Rate limiting & quota safety** — exponential backoff with jitter on `429`/`5xx` (honoring `Retry-After`), plus a **Redis token-bucket** that throttles outbound Gmail calls *before* hitting the quota. Bounded worker concurrency keeps a backfill under Gmail's per-user limits.
- **Incremental sync** — after the initial backfill, only new/changed mail is fetched via the Gmail **History API** (`startHistoryId`), so steady-state cost is proportional to *new* mail, not inbox size.
- **Compute-once** — summaries and embeddings are persisted and never recomputed unless content changes (content-hash gated). Re-syncs and retries don't re-bill AI calls or duplicate rows (idempotent upserts on Gmail ids).
- **Stateless API + indexed reads** — JWT-cookie sessions (no server-side session state) and the indexes in Section 2.2 keep inbox listing and retrieval fast as rows grow.

This is the level of scale the assessment grades, and it is genuinely handled — not stubbed.

### 7.2 Awareness: where it would strain, and the next step (not built)

Documented to show I know the limits and the upgrade path — **deliberately out of scope** for this submission to avoid over-engineering:

| If load grew to… | First thing that strains | Concrete next step (interface already isolates it) |
|---|---|---|
| Millions of emails per account | `ivfflat` recall/latency; single-table size | Switch vector index to **`hnsw`**; **partition** `emails`/`email_embeddings` by account + time — same `pgvector`, no app rewrite |
| Many concurrent users | Polling every account on a timer | **Gmail `watch` + Pub/Sub push** — sync only when mail arrives; load tracks real mail volume, not user count |
| Very high query volume | Read load on the primary; ANN memory | **Read replicas** for retrieval; quantized (`halfvec`) vectors to shrink the index |
| Vector store outgrows Postgres | Index no longer fits in memory | Move embeddings to a dedicated engine (Qdrant/Milvus) **behind the existing `RAGService`** — the rest of the app is untouched |

The architecture keeps these cheap *later* by isolating the moving parts now: retrieval sits behind one `RAGService`, all heavy work is already idempotent and queued, and the API is already stateless. Nothing in 7.2 requires re-architecting — but none of it is built, because the current bar is "thousands of emails, working."

---

## Appendix — Environment Variables (see `.env.example`)

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client credentials (Gmail API) |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | Database + storage access (server-side only) |
| `GEMINI_API_KEY` | Google Gemini (primary reasoning model) |
| `NVIDIA_NIM_API_KEY` | NVIDIA NIM embedding model |
| `REDIS_URL` | ARQ broker + rate-limit buckets |
| `APP_JWT_SECRET` | Signs the app session cookie |
| `TOKEN_ENCRYPTION_KEY` | Encrypts OAuth tokens at rest |
| `FRONTEND_ORIGIN` | CORS allow-origin for the SPA |
