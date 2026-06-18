const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export type Email = {
  id: string;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  snippet: string | null;
  summary: string | null;
  internal_date: string | null;
  is_unread: boolean;
  thread_id: string;
  category: string | null;
  priority: "urgent" | "high" | "medium" | "low" | null;
  action_item: string | null;
  needs_action: boolean;
  message_count: number;
};

export type Category = { key: string; label: string; count: number };
export type Source = { n: number; email_id: string; thread_id: string; from: string; subject: string | null; date: string };
export type SyncStatus = { status: string; phase: string | null; total_synced: number; emails: number; embedded: number };

export const api = {
  loginUrl: () => req<{ url: string }>("/auth/google/start"),
  me: () => req<{ account_id: string; email: string | null }>("/auth/me"),
  syncStatus: () => req<SyncStatus>("/sync/status"),
  triggerSync: (incremental = true) => req(`/sync?incremental=${incremental}`, { method: "POST" }),
  categories: () => req<Category[]>("/categories"),
  emails: (category?: string, offset = 0, limit = 50) =>
    req<Email[]>(
      `/emails?limit=${limit}&offset=${offset}${category ? `&category=${category}` : ""}`
    ),
  ask: (message: string, session_id?: string) =>
    req<{ session_id: string; answer: string; sources: Source[] }>("/chat/ask", {
      method: "POST",
      body: JSON.stringify({ message, session_id }),
    }),
  composeDraft: (prompt: string) =>
    req<{ subject: string; body: string }>("/compose/draft", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  replyDraft: (thread_id: string, prompt: string) =>
    req<{ subject: string; body: string }>("/compose/reply/draft", {
      method: "POST",
      body: JSON.stringify({ thread_id, prompt }),
    }),
  send: (payload: Record<string, unknown>) =>
    req<{ sent: boolean; id: string }>("/compose/send", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
