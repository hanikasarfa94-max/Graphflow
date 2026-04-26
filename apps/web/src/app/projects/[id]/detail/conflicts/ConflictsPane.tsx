"use client";

import { useEffect, useRef, useState } from "react";

import type {
  Conflict,
  ConflictSummary,
  Decision,
  ProjectState,
} from "@/lib/api";

type WsFrame = { type: string; payload: Record<string, unknown> };

type Member = ProjectState["members"][number];

const SEVERITY_COLOR: Record<Conflict["severity"], string> = {
  critical: "var(--wg-accent)",
  high: "#d97706",
  medium: "#4a7ac7",
  low: "var(--wg-ink-soft)",
};

const SEVERITY_RANK: Record<Conflict["severity"], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export function ConflictsPane({
  projectId,
  initialConflicts,
  initialSummary,
  initialDecisions,
  initialMembers,
}: {
  projectId: string;
  initialConflicts: Conflict[];
  initialSummary: ConflictSummary;
  initialDecisions: Decision[];
  initialMembers: Member[];
}) {
  const [conflicts, setConflicts] = useState<Conflict[]>(initialConflicts);
  const [summary, setSummary] = useState<ConflictSummary>(initialSummary);
  const [decisions, setDecisions] = useState<Decision[]>(initialDecisions);
  const [members] = useState<Member[]>(initialMembers);
  const [wsState, setWsState] = useState<"connecting" | "open" | "closed">(
    "connecting",
  );
  const [rechecking, setRechecking] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${window.location.host}/ws/projects/${projectId}`,
    );
    setWsState("connecting");
    ws.onopen = () => setWsState("open");
    ws.onclose = () => setWsState("closed");
    ws.onerror = () => setWsState("closed");
    ws.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as WsFrame;
        if (frame.type === "conflicts") {
          const p = frame.payload as unknown as {
            conflicts: Conflict[];
            summary: ConflictSummary;
          };
          setConflicts(p.conflicts);
          setSummary(p.summary);
        } else if (frame.type === "conflict") {
          const c = frame.payload as unknown as Conflict;
          setConflicts((prev) => {
            const idx = prev.findIndex((x) => x.id === c.id);
            if (idx === -1) return [...prev, c];
            const next = prev.slice();
            next[idx] = c;
            return next;
          });
        } else if (frame.type === "decision") {
          const d = frame.payload as unknown as Decision;
          setDecisions((prev) => {
            const idx = prev.findIndex((x) => x.id === d.id);
            if (idx === -1) return [d, ...prev];
            const next = prev.slice();
            next[idx] = d;
            return next;
          });
        }
      } catch {
        // ignore malformed frame
      }
    };
    return () => ws.close();
  }, [projectId]);

  useEffect(() => {
    if (!showClosed) return;
    (async () => {
      const res = await fetch(
        `/api/projects/${projectId}/conflicts?include_closed=true`,
        { credentials: "include", cache: "no-store" },
      );
      if (!res.ok) return;
      const body = await res.json();
      if (mounted.current) {
        setConflicts(body.conflicts ?? []);
        setSummary(body.summary ?? summary);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showClosed, projectId]);

  async function recheck() {
    setRechecking(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/projects/${projectId}/conflicts/recheck`,
        { method: "POST", credentials: "include" },
      );
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `recheck failed (${res.status})`);
      }
    } finally {
      setRechecking(false);
    }
  }

  async function submitDecision(
    conflict: Conflict,
    payload: {
      option_index: number | null;
      custom_text: string | null;
      rationale: string;
      assignee_user_id: string | null;
    },
  ) {
    setBusyId(conflict.id);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        rationale: payload.rationale,
      };
      if (payload.option_index !== null) body.option_index = payload.option_index;
      if (payload.custom_text !== null) body.custom_text = payload.custom_text;
      if (payload.assignee_user_id)
        body.assignee_user_id = payload.assignee_user_id;

      const res = await fetch(`/api/conflicts/${conflict.id}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `decision failed (${res.status})`);
        return;
      }
      const rb = await res.json();
      if (rb.conflict) {
        setConflicts((prev) =>
          prev.map((c) => (c.id === conflict.id ? rb.conflict : c)),
        );
      }
      if (rb.decision) {
        setDecisions((prev) => [rb.decision, ...prev]);
      }
    } finally {
      setBusyId(null);
    }
  }

  async function dismissConflict(conflict: Conflict) {
    setBusyId(conflict.id);
    setError(null);
    try {
      const res = await fetch(`/api/conflicts/${conflict.id}/dismiss`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `dismiss failed (${res.status})`);
        return;
      }
      const body = await res.json();
      if (body.conflict) {
        setConflicts((prev) =>
          prev.map((c) => (c.id === conflict.id ? body.conflict : c)),
        );
      }
    } finally {
      setBusyId(null);
    }
  }

  const visible = [...conflicts].sort((a, b) => {
    const sa = SEVERITY_RANK[a.severity] ?? 9;
    const sb = SEVERITY_RANK[b.severity] ?? 9;
    if (sa !== sb) return sa - sb;
    return (b.created_at ?? "").localeCompare(a.created_at ?? "");
  });

  const memberById = new Map(members.map((m) => [m.user_id, m]));
  const decisionsByConflict = new Map<string, Decision[]>();
  for (const d of decisions) {
    // IM-originated decisions have conflict_id=null; skip them here.
    if (!d.conflict_id) continue;
    const arr = decisionsByConflict.get(d.conflict_id) ?? [];
    arr.push(d);
    decisionsByConflict.set(d.conflict_id, arr);
  }

  return (
    <section style={{ display: "grid", gap: 14 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 14px",
          background: "var(--wg-surface)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
          color: "var(--wg-ink-soft)",
        }}
      >
        <span>
          <StatusDot state={wsState} /> {wsState}
        </span>
        <span data-testid="conflict-summary">
          {summary.open} open · {summary.critical} crit · {summary.high} high ·{" "}
          {summary.medium} med · {summary.low} low
        </span>
        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            marginLeft: "auto",
            cursor: "pointer",
          }}
        >
          <input
            type="checkbox"
            checked={showClosed}
            onChange={(e) => setShowClosed(e.target.checked)}
          />
          show closed
        </label>
        <button
          type="button"
          onClick={recheck}
          disabled={rechecking}
          data-testid="recheck-btn"
          style={ghostBtn}
        >
          {rechecking ? "rechecking…" : "recheck"}
        </button>
      </div>

      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}

      {visible.length === 0 && (
        <div
          style={{
            padding: 32,
            textAlign: "center",
            color: "var(--wg-ink-soft)",
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            fontSize: 14,
          }}
        >
          No conflicts detected. Detection runs after each plan and assignment
          change.
        </div>
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {visible.map((c) => (
          <ConflictCard
            key={c.id}
            conflict={c}
            busy={busyId === c.id}
            members={members}
            memberById={memberById}
            history={decisionsByConflict.get(c.id) ?? []}
            onSubmitDecision={(payload) => submitDecision(c, payload)}
            onDismiss={() => dismissConflict(c)}
          />
        ))}
      </div>
    </section>
  );
}

function ConflictCard({
  conflict,
  busy,
  members,
  memberById,
  history,
  onSubmitDecision,
  onDismiss,
}: {
  conflict: Conflict;
  busy: boolean;
  members: Member[];
  memberById: Map<string, Member>;
  history: Decision[];
  onSubmitDecision: (payload: {
    option_index: number | null;
    custom_text: string | null;
    rationale: string;
    assignee_user_id: string | null;
  }) => void;
  onDismiss: () => void;
}) {
  const color = SEVERITY_COLOR[conflict.severity];
  const closed =
    conflict.status === "resolved" ||
    conflict.status === "dismissed" ||
    conflict.status === "stale";

  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [customText, setCustomText] = useState("");
  const [rationale, setRationale] = useState("");
  const [assignee, setAssignee] = useState<string>("");

  const needsAssignee = conflict.rule === "missing_owner";
  const hasOption = selectedOption !== null;
  const hasText = customText.trim().length > 0;

  function handleSubmit() {
    if (!hasOption && !hasText) return;
    if (hasOption && hasText) return;
    onSubmitDecision({
      option_index: hasOption ? selectedOption : null,
      custom_text: hasText ? customText.trim() : null,
      rationale: rationale.trim(),
      assignee_user_id: needsAssignee && assignee ? assignee : null,
    });
  }

  return (
    <article
      data-testid="conflict-card"
      data-rule={conflict.rule}
      data-status={conflict.status}
      style={{
        border: "1px solid var(--wg-line)",
        borderLeft: `4px solid ${color}`,
        borderRadius: "var(--wg-radius)",
        background: closed ? "var(--wg-surface)" : "#fff",
        padding: 14,
        opacity: closed ? 0.7 : 1,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          marginBottom: 6,
        }}
      >
        <span
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            color,
            fontWeight: 700,
          }}
        >
          {conflict.severity} · {conflict.rule}
        </span>
        <span
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            color: "var(--wg-ink-soft)",
          }}
        >
          {conflict.status}
        </span>
      </header>

      <p
        style={{
          fontSize: 14,
          margin: "4px 0 10px",
          whiteSpace: "pre-wrap",
          color: "var(--wg-ink)",
        }}
      >
        {conflict.summary || (
          <span style={{ color: "var(--wg-ink-soft)", fontStyle: "italic" }}>
            explanation pending…
          </span>
        )}
      </p>

      {conflict.targets.length > 0 && (
        <div
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            marginBottom: 8,
            wordBreak: "break-all",
          }}
        >
          targets: {conflict.targets.join(", ")}
        </div>
      )}

      {conflict.options.length > 0 && (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: "6px 0 10px",
            display: "grid",
            gap: 6,
          }}
        >
          {conflict.options.map((o, idx) => {
            const chosen = conflict.resolved_option_index === idx;
            const picked = selectedOption === idx;
            return (
              <li
                key={idx}
                style={{
                  padding: "8px 10px",
                  border:
                    chosen || picked
                      ? "1px solid var(--wg-accent)"
                      : "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                  background:
                    chosen || picked ? "#fdecec" : "var(--wg-surface)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 10,
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 13 }}>
                    {idx + 1}. {o.label}
                  </div>
                  {!closed && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setSelectedOption(picked ? null : idx);
                        setCustomText("");
                      }}
                      data-testid={`select-option-${idx}`}
                      style={picked ? primaryBtn : ghostBtn}
                    >
                      {picked ? "selected" : "select"}
                    </button>
                  )}
                </div>
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--wg-ink-soft)",
                    marginTop: 3,
                  }}
                >
                  {o.detail}
                </div>
                {o.impact && (
                  <div
                    style={{
                      fontFamily: "var(--wg-font-mono)",
                      fontSize: 11,
                      color: "var(--wg-ink-soft)",
                      marginTop: 4,
                    }}
                  >
                    impact: {o.impact}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {!closed && (
        <div style={{ display: "grid", gap: 8, marginTop: 6 }}>
          <textarea
            data-testid="custom-text"
            placeholder="Or describe a custom resolution…"
            value={customText}
            onChange={(e) => {
              setCustomText(e.target.value);
              if (e.target.value.trim()) setSelectedOption(null);
            }}
            rows={2}
            style={inputStyle}
          />
          <textarea
            data-testid="rationale"
            placeholder="Rationale (why this decision) — optional but encouraged"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            rows={2}
            style={inputStyle}
          />
          {needsAssignee && (
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 12,
                color: "var(--wg-ink-soft)",
              }}
            >
              assignee:
              <select
                data-testid="assignee-select"
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                style={{ ...inputStyle, flex: 1 }}
              >
                <option value="">— unassigned (advisory) —</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.display_name || m.username}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDismiss()}
              data-testid="dismiss-btn"
              style={ghostBtn}
            >
              dismiss
            </button>
            <button
              type="button"
              disabled={busy || (!hasOption && !hasText) || (hasOption && hasText)}
              onClick={handleSubmit}
              data-testid="submit-decision"
              style={primaryBtn}
            >
              submit decision
            </button>
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div
          data-testid="decision-history"
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: "1px dashed var(--wg-line)",
          }}
        >
          <div
            style={{
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              color: "var(--wg-ink-soft)",
              marginBottom: 6,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            decisions ({history.length})
          </div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 6 }}>
            {history.map((d) => (
              <li
                key={d.id}
                data-testid="decision-entry"
                style={{
                  fontSize: 12,
                  padding: "6px 8px",
                  background: "var(--wg-surface)",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                }}
              >
                <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                  <span
                    style={{
                      fontFamily: "var(--wg-font-mono)",
                      fontSize: 10,
                      textTransform: "uppercase",
                      color: outcomeColor(d.apply_outcome),
                      fontWeight: 700,
                    }}
                  >
                    {d.apply_outcome}
                  </span>
                  {d.option_index !== null && (
                    <span style={{ color: "var(--wg-ink-soft)" }}>
                      option {d.option_index + 1}
                    </span>
                  )}
                  {d.custom_text && (
                    <span style={{ color: "var(--wg-ink-soft)" }}>custom</span>
                  )}
                  <span
                    style={{
                      marginLeft: "auto",
                      color: "var(--wg-ink-soft)",
                      fontFamily: "var(--wg-font-mono)",
                      fontSize: 10,
                    }}
                  >
                    {d.resolver_id && memberById.get(d.resolver_id)
                      ? memberById.get(d.resolver_id)?.display_name ||
                        memberById.get(d.resolver_id)?.username
                      : (d.resolver_id ?? "—")}{" "}
                    · {d.created_at?.slice(0, 16).replace("T", " ") ?? ""}
                  </span>
                </div>
                {d.rationale && (
                  <div
                    style={{
                      marginTop: 4,
                      whiteSpace: "pre-wrap",
                      color: "var(--wg-ink)",
                    }}
                  >
                    {d.rationale}
                  </div>
                )}
                {d.custom_text && (
                  <div
                    style={{
                      marginTop: 4,
                      whiteSpace: "pre-wrap",
                      color: "var(--wg-ink)",
                      fontStyle: "italic",
                    }}
                  >
                    “{d.custom_text}”
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

function StatusDot({ state }: { state: "connecting" | "open" | "closed" }) {
  const color =
    state === "open"
      ? "#7ab87a"
      : state === "connecting"
        ? "#d97706"
        : "var(--wg-accent)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        marginRight: 4,
        verticalAlign: "middle",
      }}
    />
  );
}

function outcomeColor(outcome: Decision["apply_outcome"]): string {
  switch (outcome) {
    case "ok":
      return "#4a8a4a";
    case "partial":
      return "#d97706";
    case "failed":
      return "var(--wg-accent)";
    case "advisory":
      return "var(--wg-ink-soft)";
    default:
      return "var(--wg-ink-soft)";
  }
}

const primaryBtn: React.CSSProperties = {
  padding: "4px 10px",
  background: "var(--wg-accent)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};
const ghostBtn: React.CSSProperties = {
  padding: "4px 10px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  cursor: "pointer",
};
const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontFamily: "inherit",
  fontSize: 13,
  background: "#fff",
  color: "var(--wg-ink)",
  resize: "vertical",
};
const errorStyle: React.CSSProperties = {
  padding: "8px 12px",
  background: "#fdecec",
  border: "1px solid var(--wg-accent)",
  borderRadius: "var(--wg-radius)",
  fontSize: 13,
  color: "var(--wg-accent)",
};
