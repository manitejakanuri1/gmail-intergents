const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "session_token";

// On load, capture a token handed back by the OAuth redirect (#token=...),
// persist it, and strip it from the URL so it isn't left in the address bar.
(function captureToken() {
  const m = window.location.hash.match(/token=([^&]+)/);
  if (m) {
    const raw = decodeURIComponent(m[1]);
    // Only accept a well-formed JWT (header.payload.signature) before storing/using it
    if (/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(raw)) {
      localStorage.setItem(TOKEN_KEY, raw);
    }
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }
})();

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include", // keeps same-origin cookie auth working locally
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
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
