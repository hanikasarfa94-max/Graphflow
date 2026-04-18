"use client";

import { useMemo, useState } from "react";

import type { Conflict, Decision, ProjectState } from "@/lib/api";

export function ConflictCanvas({
  projectId,
  state,
  setState,
}: {
  projectId: string;
  state: ProjectState;
  setState: React.Dispatch<React.SetStateAction<ProjectState>>;
}) {
  const openConflicts = useMemo(
    () =>
      state.conflicts
        .filter((c) => c.status === "open" || c.status === "stale")
        .sort((a, b) => {
          const rank: Record<string, number> = {
            critical: 0,
            high: 1,
            medium: 2,
            low: 3,
          };
          return (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9);
        }),
    [state.conflicts],
  );

  const [focusId, setFocusId] = useState<string | null>(
    openConflicts[0]?.id ?? null,
  );

  const focused =
    openConflicts.find((c) => c.id === focusId) ?? openConflicts[0] ?? null;

  if (!focused) {
    return (
      <div
        data-testid="canvas-conflict-empty"
        style={{
          padding: 32,
          color: "var(--wg-ink-soft)",
          textAlign: "center",
        }}
      >
        No open conflicts.
      </div>
    );
  }

  return (
    <div
      data-testid="canvas-conflict"
      style={{
        display: "grid",
        gridTemplateColumns: "220px 1fr",
        height: "100%",
      }}
    >
      <aside
        style={{
          borderRight: "1px solid var(--wg-line)",
          padding: "16px 14px",
          overflow: "auto",
        }}
      >
        <div
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: 10,
          }}
        >
          Open · {openConflicts.length}
        </div>
        <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
          {openConflicts.map((c) => {
            const isActive = c.id === focused.id;
            return (
              <li key={c.id}>
                <button
                  data-testid={`conflict-queue-${c.id}`}
                  onClick={() => setFocusId(c.id)}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    padding: "10px 12px",
                    marginBottom: 6,
                    background: isActive
                      ? "var(--wg-amber-soft)"
                      : "transparent",
                    border: `1px solid ${
                      isActive ? "var(--wg-amber)" : "var(--wg-line)"
                    }`,
                    borderRadius: "var(--wg-radius-sm)",
                    cursor: "pointer",
                    color: "var(--wg-ink)",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "var(--wg-font-mono)",
                      fontSize: 10,
                      color: "var(--wg-ink-soft)",
                      marginBottom: 4,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}
                  >
                    {c.rule} · {c.severity}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      lineHeight: 1.4,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                    }}
                  >
                    {c.summary || c.rule}
                  </div>
                </button>
              </li>
            );
          })}
        </ol>
      </aside>

      <CheckpointCard
        key={focused.id}
        projectId={projectId}
        conflict={focused}
        members={state.members}
        onDecision={(decision, updatedConflict) => {
          setState((prev) => {
            const conflicts = prev.conflicts.map((x) =>
              x.id === updatedConflict.id ? updatedConflict : x,
            );
            const decisions = [decision, ...prev.decisions];
            return { ...prev, conflicts, decisions };
          });
        }}
      />
    </div>
  );
}

function CheckpointCard({
  conflict,
  members,
  onDecision,
}: {
  projectId: string;
  conflict: Conflict;
  members: ProjectState["members"];
  onDecision: (decision: Decision, conflict: Conflict) => void;
}) {
  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [customText, setCustomText] = useState("");
  const [rationale, setRationale] = useState("");
  const [assigneeUserId, setAssigneeUserId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsAssignee = conflict.rule === "missing_owner";

  async function submit() {
    const hasOption = selectedOption !== null;
    const hasText = customText.trim().length > 0;
    if (!hasOption && !hasText) {
      setError("Pick an option or write a custom resolution.");
      return;
    }
    if (!rationale.trim()) {
      setError("Rationale is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { rationale: rationale.trim() };
      if (hasOption) body.option_index = selectedOption;
      if (hasText) body.custom_text = customText.trim();
      if (needsAssignee && assigneeUserId)
        body.assignee_user_id = assigneeUserId;

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
      if (rb.conflict && rb.decision) {
        onDecision(rb.decision, rb.conflict);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="conflict-card"
      data-status={conflict.status}
      style={{
        padding: 28,
        overflow: "auto",
      }}
    >
      <article
        style={{
          border: "1px solid var(--wg-amber)",
          background: "var(--wg-amber-soft)",
          borderRadius: "var(--wg-radius)",
          padding: 24,
          maxWidth: 720,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            color: "var(--wg-amber)",
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            marginBottom: 10,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 50,
              background: "var(--wg-amber)",
            }}
          />
          Checkpoint · {conflict.rule} · {conflict.severity}
        </div>

        <h3
          data-testid="checkpoint-headline"
          style={{ margin: 0, fontSize: 20, fontWeight: 600 }}
        >
          {conflict.summary || conflict.rule}
        </h3>

        {conflict.options.length > 0 ? (
          <div style={{ marginTop: 18 }}>
            <div
              style={{
                fontFamily: "var(--wg-font-mono)",
                fontSize: 11,
                color: "var(--wg-ink-soft)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                marginBottom: 8,
              }}
            >
              Options
            </div>
            <div
              style={{ display: "flex", flexDirection: "column", gap: 8 }}
            >
              {conflict.options.map((opt, i) => (
                <button
                  key={i}
                  data-testid={`select-option-${i}`}
                  onClick={() => {
                    setSelectedOption(i);
                    setCustomText("");
                  }}
                  style={{
                    padding: "10px 14px",
                    textAlign: "left",
                    border: `1px solid ${
                      selectedOption === i
                        ? "var(--wg-accent)"
                        : "var(--wg-line)"
                    }`,
                    background:
                      selectedOption === i
                        ? "var(--wg-accent-soft)"
                        : "var(--wg-surface-raised)",
                    borderRadius: "var(--wg-radius-sm)",
                    cursor: "pointer",
                    color: "var(--wg-ink)",
                  }}
                >
                  <div style={{ fontSize: 14, fontWeight: 600 }}>
                    {i + 1}. {opt.label}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      color: "var(--wg-ink-soft)",
                      marginTop: 4,
                    }}
                  >
                    {opt.detail}
                  </div>
                  {opt.impact ? (
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--wg-ink-faint)",
                        marginTop: 4,
                        fontFamily: "var(--wg-font-mono)",
                      }}
                    >
                      {opt.impact}
                    </div>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div style={{ marginTop: 18 }}>
          <label
            htmlFor="custom-text"
            style={{
              display: "block",
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 6,
            }}
          >
            Or custom resolution
          </label>
          <textarea
            id="custom-text"
            data-testid="custom-text"
            value={customText}
            onChange={(e) => {
              setCustomText(e.target.value);
              if (e.target.value) setSelectedOption(null);
            }}
            placeholder="Describe your own resolution…"
            rows={2}
            style={{
              width: "100%",
              padding: 10,
              fontSize: 13,
              fontFamily: "var(--wg-font-sans)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm)",
              background: "var(--wg-surface-raised)",
              resize: "vertical",
              color: "var(--wg-ink)",
            }}
          />
        </div>

        <div style={{ marginTop: 14 }}>
          <label
            htmlFor="rationale"
            style={{
              display: "block",
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 6,
            }}
          >
            Rationale (required)
          </label>
          <textarea
            id="rationale"
            data-testid="rationale"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="Why this choice?"
            rows={2}
            style={{
              width: "100%",
              padding: 10,
              fontSize: 13,
              fontFamily: "var(--wg-font-sans)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm)",
              background: "var(--wg-surface-raised)",
              resize: "vertical",
              color: "var(--wg-ink)",
            }}
          />
        </div>

        {needsAssignee ? (
          <div style={{ marginTop: 14 }}>
            <label
              htmlFor="assignee"
              style={{
                display: "block",
                fontFamily: "var(--wg-font-mono)",
                fontSize: 11,
                color: "var(--wg-ink-soft)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                marginBottom: 6,
              }}
            >
              Assignee
            </label>
            <select
              id="assignee"
              data-testid="assignee-select"
              value={assigneeUserId}
              onChange={(e) => setAssigneeUserId(e.target.value)}
              style={{
                padding: "8px 10px",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius-sm)",
                fontSize: 13,
                background: "var(--wg-surface-raised)",
                color: "var(--wg-ink)",
              }}
            >
              <option value="">— pick member —</option>
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.display_name || m.username}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {error ? (
          <div
            role="alert"
            style={{
              marginTop: 14,
              padding: 10,
              background: "var(--wg-accent-soft)",
              border: "1px solid var(--wg-accent)",
              borderRadius: "var(--wg-radius-sm)",
              fontSize: 13,
            }}
          >
            {error}
          </div>
        ) : null}

        <div
          style={{
            display: "flex",
            gap: 10,
            marginTop: 18,
            alignItems: "center",
          }}
        >
          <button
            data-testid="submit-decision"
            onClick={submit}
            disabled={busy}
            style={{
              padding: "10px 18px",
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--wg-radius)",
              fontWeight: 600,
              fontSize: 13,
              cursor: busy ? "wait" : "pointer",
            }}
          >
            {busy ? "Submitting…" : "Approve decision"}
          </button>
          <span
            style={{
              fontSize: 12,
              color: "var(--wg-ink-soft)",
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            3 attempts · ambiguous output → your call
          </span>
        </div>
      </article>
    </section>
  );
}
