"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function NewProjectForm() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setError(null);
    setPending(true);
    try {
      const res = await fetch("/api/intake/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
        credentials: "include",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `error ${res.status}`);
        return;
      }
      const body = await res.json();
      if (body.project_id) {
        router.push(`/projects/${body.project_id}`);
        router.refresh();
      } else {
        router.refresh();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "network error");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        marginBottom: 24,
        padding: 16,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "#fff",
      }}
    >
      <label
        style={{
          display: "block",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          marginBottom: 6,
        }}
      >
        NEW INTAKE — paste a goal, the agent will parse it
      </label>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="e.g., Ship an event registration page in one week."
        style={{
          width: "100%",
          padding: "10px 12px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontFamily: "var(--wg-font-sans)",
          fontSize: 14,
          background: "var(--wg-surface)",
          resize: "vertical",
        }}
      />
      {error && (
        <div
          role="alert"
          style={{
            marginTop: 8,
            fontSize: 13,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
        <button
          type="submit"
          disabled={pending || !text.trim()}
          style={{
            padding: "8px 16px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius)",
            fontSize: 14,
            fontWeight: 600,
            cursor: pending ? "progress" : "pointer",
            opacity: pending || !text.trim() ? 0.6 : 1,
          }}
        >
          {pending ? "parsing…" : "Intake →"}
        </button>
      </div>
    </form>
  );
}
