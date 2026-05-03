"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { ProjectState } from "@/lib/api";

export function MessagesCanvas({
  projectId,
  state,
}: {
  projectId: string;
  state: ProjectState;
}) {
  const t = useTranslations("qaSweep.consoleLegacy");
  const [answering, setAnswering] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [planning, setPlanning] = useState(false);

  const unanswered = state.clarifications.filter((c) => !c.answer);
  const answered = state.clarifications.filter((c) => c.answer);

  async function submitAnswer(questionId: string, answer: string) {
    if (!answer.trim()) return;
    setBusy(true);
    try {
      await fetch(`/api/projects/${projectId}/clarify-reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ question_id: questionId, answer }),
      });
      setAnswering(null);
    } finally {
      setBusy(false);
    }
  }

  async function runPlanner() {
    setPlanning(true);
    try {
      await fetch(`/api/projects/${projectId}/plan`, {
        method: "POST",
        credentials: "include",
      });
    } finally {
      setPlanning(false);
    }
  }

  return (
    <div
      data-testid="canvas-messages"
      style={{ maxWidth: 760, margin: "0 auto", padding: "28px 32px" }}
    >
      <SectionHeading>{t("intake")}</SectionHeading>
      <RequirementSummary state={state} />

      <SectionHeading>{t("clarifications")}</SectionHeading>

      {answered.map((c) => (
        <Message
          key={c.id}
          role="assistant"
          label="clarification"
          body={c.question}
          follow={c.answer ?? undefined}
        />
      ))}

      {unanswered.length === 0 ? (
        <div
          data-testid="no-clarifications"
          style={{
            padding: 16,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-soft)",
            fontSize: 13,
          }}
        >
          {state.plan.tasks.length > 0
            ? "All clarifications answered."
            : "No clarifications raised. Ready to plan."}
          {state.plan.tasks.length === 0 ? (
            <button
              data-testid="run-planner"
              onClick={runPlanner}
              disabled={planning}
              style={{
                marginTop: 12,
                marginLeft: 0,
                padding: "8px 14px",
                background: "var(--wg-accent)",
                color: "#fff",
                border: "none",
                borderRadius: "var(--wg-radius)",
                fontWeight: 600,
                fontSize: 13,
                cursor: planning ? "wait" : "pointer",
                display: "block",
              }}
            >
              {planning ? "Planning…" : "Run planner"}
            </button>
          ) : null}
        </div>
      ) : (
        unanswered.map((c) => (
          <Message
            key={c.id}
            role="assistant"
            label="clarification"
            body={c.question}
            action={
              answering === c.id ? (
                <AnswerForm
                  busy={busy}
                  onCancel={() => setAnswering(null)}
                  onSubmit={(text) => submitAnswer(c.id, text)}
                />
              ) : (
                <button
                  data-testid={`answer-${c.position}`}
                  onClick={() => setAnswering(c.id)}
                  style={{
                    padding: "6px 12px",
                    background: "transparent",
                    border: "1px solid var(--wg-line)",
                    borderRadius: "var(--wg-radius-sm)",
                    fontSize: 12,
                    cursor: "pointer",
                    color: "var(--wg-ink)",
                  }}
                >
                  Answer
                </button>
              )
            }
          />
        ))
      )}
    </div>
  );
}

function RequirementSummary({ state }: { state: ProjectState }) {
  const parsed = state.parsed as Record<string, unknown>;
  const scope = Array.isArray(parsed.scope_items)
    ? (parsed.scope_items as string[])
    : [];
  const goal = typeof parsed.goal === "string" ? parsed.goal : null;

  return (
    <div
      data-testid="requirement-summary"
      style={{
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        padding: 16,
        background: "var(--wg-surface-raised)",
        marginBottom: 28,
      }}
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        {state.project.title}
      </div>
      {goal ? (
        <p style={{ margin: "0 0 12px", fontSize: 15 }}>{goal}</p>
      ) : null}
      {scope.length > 0 ? (
        <ul
          data-testid="scope-items"
          style={{ margin: 0, padding: 0, listStyle: "none" }}
        >
          {scope.map((item, i) => (
            <li
              key={`${item}-${i}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "4px 0",
                fontSize: 14,
              }}
            >
              <span className="wg-dot" aria-hidden />
              {item}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Message({
  role,
  label,
  body,
  follow,
  action,
}: {
  role: "assistant" | "user";
  label: string;
  body: string;
  follow?: string;
  action?: React.ReactNode;
}) {
  return (
    <article
      data-testid="message"
      data-role={role}
      style={{
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        padding: 14,
        marginBottom: 12,
        background: role === "assistant"
          ? "var(--wg-surface-raised)"
          : "var(--wg-surface-sunk)",
      }}
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 10,
          color: "var(--wg-ink-soft)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 14 }}>{body}</div>
      {follow ? (
        <div
          style={{
            marginTop: 10,
            padding: "10px 12px",
            background: "var(--wg-surface-sunk)",
            borderLeft: "2px solid var(--wg-accent)",
            fontSize: 14,
          }}
        >
          {follow}
        </div>
      ) : null}
      {action ? <div style={{ marginTop: 12 }}>{action}</div> : null}
    </article>
  );
}

function AnswerForm({
  busy,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState("");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <textarea
        data-testid="answer-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Your answer…"
        rows={3}
        style={{
          padding: 8,
          fontSize: 13,
          fontFamily: "var(--wg-font-sans)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius-sm)",
          resize: "vertical",
          background: "var(--wg-surface-raised)",
          color: "var(--wg-ink)",
        }}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <button
          data-testid="submit-answer"
          onClick={() => onSubmit(text)}
          disabled={busy || !text.trim()}
          style={{
            padding: "6px 12px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius-sm)",
            fontSize: 12,
            fontWeight: 600,
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "Sending…" : "Submit"}
        </button>
        <button
          onClick={onCancel}
          style={{
            padding: "6px 12px",
            background: "transparent",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm)",
            fontSize: 12,
            cursor: "pointer",
            color: "var(--wg-ink-soft)",
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      style={{
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        color: "var(--wg-ink-soft)",
        textTransform: "uppercase",
        letterSpacing: "0.12em",
        fontWeight: 600,
        marginTop: 0,
        marginBottom: 14,
      }}
    >
      {children}
    </h2>
  );
}
