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

  // Card chrome lives in the parent (see /projects page) — this form
  // is now flush content. The intake textarea is the only field; the
  // submit posts to /api/intake/message which both creates a project
  // (when none matches) and pushes the message into intake routing.
  return (
    <form onSubmit={handleSubmit}>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        placeholder="e.g., Ship an event registration page in one week."
        style={{
          width: "100%",
          padding: "12px 14px",
          border: "1px solid var(--wg-line)",
          borderRadius: 14,
          fontFamily: "var(--wg-font-sans)",
          fontSize: 14,
          background: "var(--wg-surface)",
          resize: "vertical",
          color: "var(--wg-ink)",
        }}
      />
      {error && (
        <div
          role="alert"
          style={{
            marginTop: 8,
            fontSize: 13,
            color: "var(--wg-danger)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
        <button
          type="submit"
          disabled={pending || !text.trim()}
          style={{
            padding: "9px 18px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: 12,
            fontSize: 13,
            fontWeight: 700,
            cursor: pending ? "progress" : "pointer",
            opacity: pending || !text.trim() ? 0.6 : 1,
            boxShadow: "0 6px 14px rgba(37,99,235,0.22)",
          }}
        >
          {pending ? "parsing…" : "Intake →"}
        </button>
      </div>
    </form>
  );
}
