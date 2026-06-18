# AI-Powered Gmail Intelligence Platform

A web app that connects to your Gmail, syncs and enriches your mail with AI
(summaries, categories, embeddings), and lets you **chat with your inbox** — a
RAG agent that answers from your emails with source citations and won't hallucinate.

Built for the Repeatless technical assessment. See [`Architecture.md`](Architecture.md)
for the full system/AI/DB design.

## Features

- **Gmail integration** — OAuth 2.0, paginated sync, 429/backoff handling, incremental sync via the History API
- **AI triage (one call/email)** — category + priority + summary + action item in a single Gemini call
- **Priority control dashboard** — emails stacked by urgency (urgent→low) with per-item "Do:" actions and Done reminders; switchable Gmail-list / Table / To-do views (remembered per user)
- **Categorization** — Newsletters / Job / Finance / Notifications / Personal / Work
- **AI chat agent** — RAG over your emails with cited sources, a "not found" guardrail, and graceful fallback when a model is rate-limited
- **Compose & reply** — draft from a prompt; replies preserve `In-Reply-To` / `References` so Gmail threads them

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + TypeScript |
| Backend | FastAPI (async Python) |
| Worker | ARQ (Redis queue) |
| Database | Supabase (Postgres + pgvector) |
| Primary AI | Google Gemini |
| Secondary AI | NVIDIA NIM (`nv-embedqa-e5-v5`) embeddings |

## Repository structure

```
repeat/
├── Architecture.md            # design document (system, DB, AI, Gmail, trade-offs)
├── backend/
│   ├── migrations/001_init.sql  # Supabase schema (run once)
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── main.py            # FastAPI app + lifespan (db pool, arq pool)
│       ├── config.py          # settings from env
│       ├── db.py              # asyncpg pool + pgvector helpers
│       ├── security.py        # JWT sessions + token encryption (Fernet)
│       ├── deps.py            # auth dependency
│       ├── routers/           # auth, sync, emails, threads, categories, compose, chat
│       ├── services/          # gmail, ai_gemini, ai_nim, parsing, categorize,
│       │                      #   summarize, rag, accounts, sync
│       └── workers/tasks.py   # ARQ jobs: sync_account, enrich_email
└── frontend/
    ├── .env.example
    └── src/                   # App.tsx (3-pane UI), api.ts, styles.css
```

## Prerequisites

- Python 3.11+, Node 18+, and a running **Redis** (local or Upstash)
- A **Supabase** project (Postgres + pgvector)
- **Google Cloud** OAuth client (Gmail API enabled)
- **Gemini** API key and **NVIDIA NIM** API key (both have free tiers)

## Setup

### 1. Database

In the Supabase SQL editor, run [`backend/migrations/001_init.sql`](backend/migrations/001_init.sql)
then [`backend/migrations/002_priority.sql`](backend/migrations/002_priority.sql). The first enables
`vector` + `pgcrypto` and creates all tables/indexes; the second adds the priority/action columns
that power the control dashboard.

### 2. Google OAuth

In Google Cloud Console: enable the **Gmail API**, create an **OAuth 2.0 Client
ID** (Web application), and add the redirect URI
`http://localhost:8000/auth/google/callback`. Add yourself as a test user.

### 3. Backend

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env        # then fill in the values
uvicorn app.main:app --reload --port 8000
```

In a second terminal, start the worker (same venv + `.env`):

```bash
arq app.workers.tasks.WorkerSettings
```

### 4. Frontend

```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_URL=http://localhost:8000
npm run dev                 # http://localhost:5173
```

### 5. Use it

Open `http://localhost:5173`, click **Connect Gmail**, approve access. The
initial sync runs in the background (the sidebar shows progress); as emails are
enriched they gain summaries, categories, and embeddings. Then browse the inbox,
ask the chat agent questions, or compose an email.

## Environment variables

### Backend (`backend/.env`)

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth client credentials |
| `GOOGLE_REDIRECT_URI` | OAuth callback (`http://localhost:8000/auth/google/callback`) |
| `DATABASE_URL` | Supabase Postgres DSN (asyncpg) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | Supabase project (optional helpers) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Gemini key + model (`gemini-2.0-flash`) |
| `NVIDIA_NIM_API_KEY` / `NIM_EMBED_MODEL` / `NIM_BASE_URL` | NIM embedding config |
| `REDIS_URL` | Redis for the ARQ queue |
| `APP_JWT_SECRET` | Signs the session cookie |
| `TOKEN_ENCRYPTION_KEY` | Encrypts OAuth tokens at rest |
| `FRONTEND_ORIGIN` | CORS origin (`http://localhost:5173`) |

### Frontend (`frontend/.env`)

| Variable | Description |
|---|---|
| `VITE_API_URL` | Backend base URL |

## Notes & limitations

The initial sync is capped (`INITIAL_LIMIT` in `app/services/sync.py`) to keep
the demo fast and within quota — raise it for a fuller backfill. See the
**Trade-offs & Limitations** and **Scalability** sections of `Architecture.md`
for what is intentionally simplified and the growth path.
