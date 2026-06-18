-- AI Gmail Intelligence Platform — initial schema
-- Run this in the Supabase SQL editor (or psql) once before starting the app.

create extension if not exists vector;
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Users + connected Gmail accounts
-- ---------------------------------------------------------------------------
create table if not exists users (
  id           uuid primary key default gen_random_uuid(),
  email        text unique not null,
  display_name text,
  created_at   timestamptz not null default now()
);

create table if not exists gmail_accounts (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references users(id) on delete cascade,
  google_email      text not null,
  access_token_enc  bytea not null,
  refresh_token_enc bytea not null,
  token_expiry      timestamptz,
  history_id        bigint,
  created_at        timestamptz not null default now(),
  unique (user_id, google_email)
);

-- ---------------------------------------------------------------------------
-- Category taxonomy (defined before emails so the FK resolves cleanly)
-- ---------------------------------------------------------------------------
create table if not exists categories (
  id         uuid primary key default gen_random_uuid(),
  account_id uuid references gmail_accounts(id) on delete cascade,
  key        text not null,
  label      text not null,
  is_system  boolean default true,
  unique (account_id, key)
);

-- ---------------------------------------------------------------------------
-- Labels mirrored from Gmail
-- ---------------------------------------------------------------------------
create table if not exists labels (
  id             uuid primary key default gen_random_uuid(),
  account_id     uuid not null references gmail_accounts(id) on delete cascade,
  gmail_label_id text not null,
  name           text not null,
  type           text,
  unique (account_id, gmail_label_id)
);

-- ---------------------------------------------------------------------------
-- Threads (first-class) + emails
-- ---------------------------------------------------------------------------
create table if not exists threads (
  id              uuid primary key default gen_random_uuid(),
  account_id      uuid not null references gmail_accounts(id) on delete cascade,
  gmail_thread_id text not null,
  subject         text,
  last_message_at timestamptz,
  message_count   int default 0,
  summary         text,
  summary_model   text,
  updated_at      timestamptz not null default now(),
  unique (account_id, gmail_thread_id)
);

create table if not exists emails (
  id                uuid primary key default gen_random_uuid(),
  account_id        uuid not null references gmail_accounts(id) on delete cascade,
  thread_id         uuid not null references threads(id) on delete cascade,
  gmail_message_id  text not null,
  rfc822_message_id text,
  from_email        text,
  from_name         text,
  to_emails         text[],
  cc_emails         text[],
  subject           text,
  snippet           text,
  body_text         text,
  body_html         text,
  internal_date     timestamptz,
  is_unread         boolean default true,
  category_id       uuid references categories(id) on delete set null,
  summary           text,
  summary_model     text,
  label_ids         text[],
  created_at        timestamptz not null default now(),
  unique (account_id, gmail_message_id)
);

-- ---------------------------------------------------------------------------
-- Vector store for RAG (chunked)
-- ---------------------------------------------------------------------------
create table if not exists email_embeddings (
  id          uuid primary key default gen_random_uuid(),
  account_id  uuid not null references gmail_accounts(id) on delete cascade,
  email_id    uuid not null references emails(id) on delete cascade,
  thread_id   uuid not null references threads(id) on delete cascade,
  chunk_index int not null default 0,
  content     text not null,
  embedding   vector(1024) not null,
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Chat agent
-- ---------------------------------------------------------------------------
create table if not exists chat_sessions (
  id         uuid primary key default gen_random_uuid(),
  account_id uuid not null references gmail_accounts(id) on delete cascade,
  title      text,
  created_at timestamptz not null default now()
);

create table if not exists chat_messages (
  id         uuid primary key default gen_random_uuid(),
  session_id uuid not null references chat_sessions(id) on delete cascade,
  role       text not null,
  content    text not null,
  sources    jsonb,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Sync bookkeeping
-- ---------------------------------------------------------------------------
create table if not exists sync_state (
  account_id     uuid primary key references gmail_accounts(id) on delete cascade,
  status         text not null default 'idle',
  phase          text,
  page_token     text,
  last_synced_at timestamptz,
  total_synced   int default 0,
  error          text
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
create index if not exists idx_emails_account_date on emails (account_id, internal_date desc);
create index if not exists idx_emails_thread on emails (thread_id);
create index if not exists idx_emails_category on emails (category_id);
create index if not exists idx_threads_account_last on threads (account_id, last_message_at desc);
create index if not exists idx_embeddings_account on email_embeddings (account_id);

-- Vector ANN index (cosine).
create index if not exists idx_embeddings_vec
  on email_embeddings using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- Full-text column + GIN index for hybrid search.
alter table emails add column if not exists tsv tsvector
  generated always as (to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(body_text,''))) stored;
create index if not exists idx_emails_tsv on emails using gin (tsv);
