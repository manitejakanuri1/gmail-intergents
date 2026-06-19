import { useEffect, useRef, useState } from "react";
import { api, Category, Email, Source, SyncStatus } from "./api";
import Landing from "./Landing";

type ViewMode = "priority" | "list" | "table" | "todo";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.me().then((m) => { setAuthed(true); setEmail(m.email); }).catch(() => setAuthed(false));
  }, []);

  const connect = async () => {
    setBusy(true);
    try {
      const { url } = await api.loginUrl();
      // Only ever redirect to Google's OAuth domain (guards against open redirect)
      if (/^https:\/\/accounts\.google\.com\//.test(url)) {
        window.location.href = url;
      } else {
        throw new Error("Unexpected login URL");
      }
    } catch {
      setBusy(false);
      alert("Couldn't reach the backend. Please try again in a moment (the server may be waking up).");
    }
  };

  if (authed === null) return <div className="center muted">Loading…</div>;
  if (!authed) return <Landing onConnect={connect} busy={busy} />;
  return <Dashboard email={email} />;
}

function Dashboard({ email }: { email: string | null }) {
  const [cats, setCats] = useState<Category[]>([]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [view, setView] = useState<"inbox" | "compose">("inbox");
  const [viewMode, setViewMode] = useState<ViewMode>(
    () => (localStorage.getItem("viewMode") as ViewMode) || "priority"
  );
  const changeViewMode = (m: ViewMode) => {
    setViewMode(m);
    localStorage.setItem("viewMode", m);
  };

  const [hasMore, setHasMore] = useState(false);

  // Refs so the polling interval always reads the *current* filter, not a
  // stale value captured when the interval was created.
  const activeRef = useRef<string | null>(null);
  const lastCount = useRef<number>(-1);
  const expandedRef = useRef<boolean>(false); // true once the user clicks "Load more"

  const PAGE = 50;

  const loadFirst = async (category?: string) => {
    expandedRef.current = false;
    const data = await api.emails(category, 0, PAGE);
    setEmails(data);
    setHasMore(data.length === PAGE);
  };

  const loadMore = async () => {
    expandedRef.current = true;
    const data = await api.emails(activeRef.current ?? undefined, emails.length, PAGE);
    setEmails((prev) => [...prev, ...data]);
    setHasMore(data.length === PAGE);
  };

  useEffect(() => {
    api.categories().then(setCats);
    loadFirst();
    const poll = setInterval(async () => {
      const s = await api.syncStatus();
      setSync(s);
      // Refresh the list when new emails arrived — but don't disrupt a user
      // who has paged through with "Load more".
      if (s.emails !== lastCount.current) {
        lastCount.current = s.emails;
        api.categories().then(setCats);
        if (!expandedRef.current) loadFirst(activeRef.current ?? undefined);
      }
    }, 4000);
    return () => clearInterval(poll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pick = (c: string | null) => {
    setActive(c);
    activeRef.current = c;
    setView("inbox");
    loadFirst(c ?? undefined);
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">📧 Inbox AI</div>
        <div className="acct muted">{email}</div>
        <nav>
          <button className={view === "inbox" && !active ? "nav active" : "nav"} onClick={() => pick(null)}>Inbox</button>
          <button className={view === "compose" ? "nav active" : "nav"} onClick={() => setView("compose")}>Compose</button>
        </nav>
        <div className="section-label">Categories</div>
        {cats.map((c) => (
          <button key={c.key} className={active === c.key ? "cat active" : "cat"} onClick={() => pick(c.key)}>
            <span>{c.label}</span><span className="muted">{c.count}</span>
          </button>
        ))}
        <div className="sync muted">
          {sync ? `${sync.status} · ${sync.emails} emails · ${sync.embedded} embedded` : "…"}
        </div>
      </aside>

      <main className="main">
        {view === "compose" ? (
          <Compose />
        ) : (
          <Inbox
            emails={emails}
            viewMode={viewMode}
            onViewMode={changeViewMode}
            hasMore={hasMore}
            onLoadMore={loadMore}
          />
        )}
      </main>

      <ChatPanel />
    </div>
  );
}

const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";

const VIEW_OPTIONS: { key: ViewMode; label: string }[] = [
  { key: "priority", label: "Priority" },
  { key: "list", label: "Gmail list" },
  { key: "table", label: "Table" },
  { key: "todo", label: "To-do" },
];

const PRIORITY_META: Record<string, { label: string; rank: number }> = {
  urgent: { label: "Urgent", rank: 1 },
  high: { label: "High", rank: 2 },
  medium: { label: "Medium", rank: 3 },
  low: { label: "Low", rank: 4 },
};
const prank = (p: string | null) => (p && PRIORITY_META[p] ? PRIORITY_META[p].rank : 5);

function Inbox({
  emails,
  viewMode,
  onViewMode,
  hasMore,
  onLoadMore,
}: {
  emails: Email[];
  viewMode: ViewMode;
  onViewMode: (m: ViewMode) => void;
  hasMore: boolean;
  onLoadMore: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const more = async () => {
    setLoading(true);
    try {
      await onLoadMore();
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="inbox">
      <div className="inbox-top">
        <h2>Inbox</h2>
        <div className="view-switch">
          {VIEW_OPTIONS.map((o) => (
            <button
              key={o.key}
              className={viewMode === o.key ? "vbtn active" : "vbtn"}
              onClick={() => onViewMode(o.key)}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {emails.length === 0 && (
        <p className="muted">No emails yet — sync is running in the background.</p>
      )}

      {viewMode === "priority" && <PriorityView emails={emails} />}
      {viewMode === "list" && <ListView emails={emails} />}
      {viewMode === "table" && <TableView emails={emails} />}
      {viewMode === "todo" && <TodoView emails={emails} />}

      {hasMore && (
        <div className="load-more-wrap">
          <button className="load-more" onClick={more} disabled={loading}>
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}

function ListView({ emails }: { emails: Email[] }) {
  return (
    <>
      {emails.map((e) => (
        <div className="email-card" key={e.id}>
          <div className="email-head">
            <span className="from">{e.from_name || e.from_email}</span>
            {e.category && <span className="pill">{e.category}</span>}
          </div>
          <div className="subject">{e.subject || "(no subject)"}</div>
          <div className="summary muted">
            ✨ {e.summary || e.snippet || "Summarizing…"}
            {e.message_count > 1 && <span className="thread"> · thread of {e.message_count}</span>}
          </div>
        </div>
      ))}
    </>
  );
}

function TableView({ emails }: { emails: Email[] }) {
  return (
    <table className="email-table">
      <thead>
        <tr>
          <th>From</th>
          <th>Subject</th>
          <th>Category</th>
          <th>Summary</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        {emails.map((e) => (
          <tr key={e.id}>
            <td>{e.from_name || e.from_email}</td>
            <td>{e.subject || "(no subject)"}</td>
            <td>{e.category ? <span className="pill">{e.category}</span> : "—"}</td>
            <td className="muted">{e.summary || e.snippet || "…"}</td>
            <td className="muted">{fmtDate(e.internal_date)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function useDone() {
  const [done, setDone] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem("doneItems") || "{}");
    } catch {
      return {};
    }
  });
  const toggle = (id: string) => {
    setDone((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      localStorage.setItem("doneItems", JSON.stringify(next));
      return next;
    });
  };
  return { done, toggle };
}

function PriorityView({ emails }: { emails: Email[] }) {
  const { done, toggle } = useDone();

  // Sort by urgency (urgent first), then newest. Done items sink to the bottom.
  const sorted = [...emails].sort((a, b) => {
    const da = done[a.id] ? 1 : 0;
    const db = done[b.id] ? 1 : 0;
    if (da !== db) return da - db;
    const r = prank(a.priority) - prank(b.priority);
    if (r !== 0) return r;
    return (b.internal_date || "").localeCompare(a.internal_date || "");
  });

  const order = ["urgent", "high", "medium", "low"];
  const groups = order
    .map((p) => ({ p, items: sorted.filter((e) => (e.priority || "low") === p && !done[e.id]) }))
    .filter((g) => g.items.length > 0);
  const doneItems = sorted.filter((e) => done[e.id]);

  return (
    <div className="prio">
      {groups.length === 0 && doneItems.length === 0 && (
        <p className="muted">Priorities appear here as emails are analyzed.</p>
      )}
      {groups.map(({ p, items }) => (
        <div className={`prio-group prio-${p}`} key={p}>
          <div className="prio-head">
            <span className={`prio-badge b-${p}`}>{PRIORITY_META[p].label}</span>
            <span className="muted">{items.length}</span>
          </div>
          {items.map((e) => (
            <PriorityCard key={e.id} e={e} p={p} done={false} onToggle={() => toggle(e.id)} />
          ))}
        </div>
      ))}
      {doneItems.length > 0 && (
        <div className="prio-group prio-done">
          <div className="prio-head"><span className="prio-badge b-done">Done</span><span className="muted">{doneItems.length}</span></div>
          {doneItems.map((e) => (
            <PriorityCard key={e.id} e={e} p={e.priority || "low"} done onToggle={() => toggle(e.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function PriorityCard({
  e,
  p,
  done,
  onToggle,
}: {
  e: Email;
  p: string;
  done: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={`prio-card emph-${p} ${done ? "is-done" : ""}`}>
      <div className="prio-card-main">
        <div className="email-head">
          <span className="from">{e.from_name || e.from_email}</span>
          <span className="prio-tags">
            {e.category && <span className="pill">{e.category}</span>}
          </span>
        </div>
        <div className="subject">{e.subject || "(no subject)"}</div>
        <div className="summary muted">{e.summary || e.snippet || "Analyzing…"}</div>
        {e.action_item && (
          <div className="action">
            <span className="action-label">Do:</span> {e.action_item}
          </div>
        )}
      </div>
      <button className={done ? "done-btn on" : "done-btn"} onClick={onToggle} title="Mark done / reminder">
        {done ? "↩ Undo" : "✓ Done"}
      </button>
    </div>
  );
}

function TodoView({ emails }: { emails: Email[] }) {
  // Surface emails as actionable items, grouped by category.
  const groups = emails.reduce<Record<string, Email[]>>((acc, e) => {
    const k = e.category || "uncategorized";
    (acc[k] ||= []).push(e);
    return acc;
  }, {});
  return (
    <div className="todo">
      {Object.entries(groups).map(([cat, items]) => (
        <div className="todo-group" key={cat}>
          <div className="todo-cat">{cat}</div>
          {items.map((e) => (
            <label className="todo-item" key={e.id}>
              <input type="checkbox" />
              <span>
                <strong>{e.from_name || e.from_email}</strong> — {e.summary || e.subject || e.snippet}
              </span>
            </label>
          ))}
        </div>
      ))}
    </div>
  );
}

function ChatPanel() {
  const [msgs, setMsgs] = useState<{ role: string; content: string; sources?: Source[] }[]>([]);
  const [input, setInput] = useState("");
  const [session, setSession] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    if (!input.trim() || busy) return;
    const q = input.trim();
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setBusy(true);
    try {
      const r = await api.ask(q, session);
      setSession(r.session_id);
      setMsgs((m) => [...m, { role: "assistant", content: r.answer, sources: r.sources }]);
    } catch {
      setMsgs((m) => [...m, { role: "assistant", content: "Something went wrong." }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="chat">
      <div className="chat-title">Ask your inbox</div>
      <div className="chat-body">
        {msgs.length === 0 && <p className="muted">Try: “Which companies rejected my application?”</p>}
        {msgs.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <div>{m.content}</div>
            {m.sources && m.sources.length > 0 && (
              <div className="sources">
                {m.sources.map((s) => (
                  <span className="source-chip" key={s.n}>✉ {s.from} · {s.date}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="bubble assistant muted">Thinking…</div>}
      </div>
      <div className="chat-input">
        <input
          value={input}
          placeholder="Ask anything about your mail…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
        />
        <button onClick={ask} disabled={busy}>↑</button>
      </div>
    </aside>
  );
}

function Compose() {
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const generate = async () => {
    setBusy(true);
    try { setDraft(await api.composeDraft(prompt)); } finally { setBusy(false); }
  };
  const send = async () => {
    if (!draft) return;
    setBusy(true);
    try { await api.send({ to, subject: draft.subject, body: draft.body }); setSent(true); }
    finally { setBusy(false); }
  };

  return (
    <div className="compose">
      <h2>Compose with AI</h2>
      <textarea placeholder="e.g. Write a follow-up to the product team about the Q3 launch delay"
        value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      <button className="btn-primary" onClick={generate} disabled={busy || !prompt.trim()}>
        {busy ? "Drafting…" : "Generate draft"}
      </button>
      {draft && (
        <div className="draft">
          <input placeholder="To" value={to} onChange={(e) => setTo(e.target.value)} />
          <input value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
          <textarea value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
          <button className="btn-primary" onClick={send} disabled={busy || !to.trim()}>Send</button>
          {sent && <span className="ok"> Sent ✓</span>}
        </div>
      )}
    </div>
  );
}
