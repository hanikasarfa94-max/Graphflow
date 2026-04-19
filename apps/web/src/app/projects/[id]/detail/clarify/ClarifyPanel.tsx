"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

type Question = {
  id: string;
  position: number;
  question: string;
  answer: string | null;
};

export function ClarifyPanel({
  projectId,
  initial,
}: {
  projectId: string;
  initial: Question[];
}) {
  const router = useRouter();
  const [questions, setQuestions] = useState(initial);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const open = questions.filter((q) => !q.answer);
  const answered = questions.filter((q) => q.answer);

  async function handleGenerate() {
    setError(null);
    const res = await fetch(`/api/projects/${projectId}/clarify`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(body.detail ?? `error ${res.status}`);
      return;
    }
    startTransition(() => router.refresh());
  }

  async function handleReply(q: Question) {
    const answer = (draft[q.id] ?? "").trim();
    if (!answer) return;
    setError(null);
    const res = await fetch(`/api/projects/${projectId}/clarify-reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question_id: q.id, answer }),
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(body.detail ?? `error ${res.status}`);
      return;
    }
    setQuestions((qs) =>
      qs.map((x) => (x.id === q.id ? { ...x, answer } : x)),
    );
    setDraft((d) => ({ ...d, [q.id]: "" }));
    startTransition(() => router.refresh());
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 16px",
          background: "#fff",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
        }}
      >
        <div style={{ fontSize: 14 }}>
          {open.length} open · {answered.length} answered
        </div>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={isPending}
          style={primaryBtn}
        >
          Generate clarifications
        </button>
      </div>

      {error && (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      )}

      {questions.length === 0 && (
        <div style={emptyCard}>
          No clarifications yet. Click &ldquo;Generate&rdquo; if requirements look
          ambiguous.
        </div>
      )}

      {open.map((q) => (
        <div key={q.id} style={qCard}>
          <div style={questionTitle}>
            Q{q.position}. {q.question}
          </div>
          <textarea
            value={draft[q.id] ?? ""}
            onChange={(e) =>
              setDraft((d) => ({ ...d, [q.id]: e.target.value }))
            }
            rows={3}
            placeholder="Answer…"
            style={textareaStyle}
          />
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
            <button
              type="button"
              onClick={() => handleReply(q)}
              disabled={!draft[q.id]?.trim() || isPending}
              style={primaryBtn}
            >
              Send reply
            </button>
          </div>
        </div>
      ))}

      {answered.length > 0 && (
        <details
          style={{
            padding: 12,
            background: "#fff",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
          }}
        >
          <summary
            style={{
              cursor: "pointer",
              fontSize: 13,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            Answered ({answered.length})
          </summary>
          <ul style={{ listStyle: "none", padding: 0, margin: "10px 0 0", display: "grid", gap: 10 }}>
            {answered.map((q) => (
              <li key={q.id}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  Q{q.position}. {q.question}
                </div>
                <div
                  style={{
                    marginTop: 2,
                    fontSize: 13,
                    color: "var(--wg-ink-soft)",
                  }}
                >
                  → {q.answer}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  padding: "8px 14px",
  background: "var(--wg-accent)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--wg-radius)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};
const qCard: React.CSSProperties = {
  padding: 16,
  background: "#fff",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
};
const questionTitle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  marginBottom: 10,
};
const textareaStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 14,
  fontFamily: "var(--wg-font-sans)",
  background: "var(--wg-surface)",
  resize: "vertical",
};
const errorStyle: React.CSSProperties = {
  padding: 10,
  fontSize: 13,
  color: "var(--wg-accent)",
  fontFamily: "var(--wg-font-mono)",
  border: "1px solid var(--wg-accent)",
  borderRadius: "var(--wg-radius)",
};
const emptyCard: React.CSSProperties = {
  padding: 24,
  textAlign: "center",
  color: "var(--wg-ink-soft)",
  fontSize: 14,
  border: "1px dashed var(--wg-line)",
  borderRadius: "var(--wg-radius)",
};
