"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

const CANONICAL_TEXT =
  "Ship an event registration page in one week. Needs invite-code gate, phone-number validation, admin export, and conversion tracking.";

const STAGES = [
  { id: "intake", label: "Intake", hint: "message → requirement" },
  { id: "clarify", label: "Clarify", hint: "open questions" },
  { id: "plan", label: "Plan", hint: "tasks + owners" },
  { id: "decide", label: "Decide", hint: "conflicts resolved" },
  { id: "deliver", label: "Deliver", hint: "summary + handoff" },
];

const FEATURES = [
  {
    title: "What you type",
    body: "One message. \"Ship an event page in a week, with invite-code gate and admin export.\"",
  },
  {
    title: "What we do",
    body: "Seven LLM agents parse, clarify, plan, and hand off — orchestrated as a graph, not a doc.",
  },
  {
    title: "What you get",
    body: "A live plan with owners, a conflict log with decisions, and a delivery summary when it ships.",
  },
];

export function LandingHero() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runCanonicalDemo() {
    setBusy(true);
    setError(null);
    try {
      const me = await fetch("/api/auth/me", { credentials: "include" });
      if (me.status === 401) {
        router.push(`/login?next=${encodeURIComponent("/")}`);
        return;
      }
      const res = await fetch("/api/intake/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ text: CANONICAL_TEXT }),
      });
      if (res.status === 401) {
        router.push(`/login?next=${encodeURIComponent("/")}`);
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.detail ?? `demo start failed (${res.status})`);
        return;
      }
      const body = await res.json();
      const projectId = body?.project?.id as string | undefined;
      if (!projectId) {
        setError("demo started but no project id returned");
        return;
      }
      router.push(`/console/${projectId}`);
    } catch {
      setError("network error — check the API is running");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      style={{
        padding: "72px 72px 56px",
        display: "flex",
        flexDirection: "column",
        gap: 56,
        maxWidth: 820,
      }}
    >
      {/* Brand row */}
      <div
        style={{
          fontSize: 13,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wg-ink-soft)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span className="wg-dot" />
        WorkGraph
      </div>

      {/* Hero copy */}
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <h1
          style={{
            fontSize: 48,
            lineHeight: 1.1,
            fontWeight: 600,
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          Coordination as a graph,
          <br />
          not a document.
        </h1>
        <p
          style={{
            fontSize: 18,
            lineHeight: 1.55,
            color: "var(--wg-ink-soft)",
            margin: 0,
            maxWidth: 560,
          }}
        >
          Turn a single message into a coordinated team plan. Every stage is
          a node, every handoff is an edge, and every decision is on the
          record.
        </p>

        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            marginTop: 12,
          }}
        >
          <button
            data-testid="run-canonical-demo"
            onClick={runCanonicalDemo}
            disabled={busy}
            style={{
              padding: "12px 20px",
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--wg-radius)",
              fontFamily: "var(--wg-font-sans)",
              fontSize: 15,
              fontWeight: 600,
              cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.7 : 1,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              boxShadow: "0 1px 0 rgba(0,0,0,0.04)",
            }}
          >
            {busy ? "Starting…" : "Run canonical demo"}
            <span aria-hidden>▶</span>
          </button>

          <Link
            href="/projects"
            style={{
              padding: "12px 16px",
              color: "var(--wg-ink-soft)",
              textDecoration: "none",
              fontSize: 14,
            }}
          >
            Open projects →
          </Link>
        </div>

        {error ? (
          <div
            role="alert"
            style={{
              marginTop: 4,
              padding: 12,
              background: "var(--wg-accent-soft)",
              border: "1px solid var(--wg-accent)",
              borderRadius: "var(--wg-radius)",
              fontSize: 13,
              maxWidth: 480,
            }}
          >
            {error}
          </div>
        ) : null}
      </div>

      {/* Flow strip */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "16px 18px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          background: "var(--wg-surface-raised)",
          overflowX: "auto",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
        }}
      >
        {STAGES.map((s, i) => (
          <span
            key={s.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexShrink: 0,
            }}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 10px",
                borderRadius: 999,
                background: "var(--wg-surface-sunk)",
                color: "var(--wg-ink)",
                border: "1px solid var(--wg-line)",
              }}
            >
              <span className="wg-dot" />
              {s.label}
              <span style={{ color: "var(--wg-ink-faint)" }}>— {s.hint}</span>
            </span>
            {i < STAGES.length - 1 ? (
              <span style={{ color: "var(--wg-ink-faint)" }}>→</span>
            ) : null}
          </span>
        ))}
      </div>

      {/* What it does — 3-up */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 16,
        }}
      >
        {FEATURES.map((f) => (
          <div
            key={f.title}
            style={{
              padding: "20px 18px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              background: "var(--wg-surface-raised)",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div
              style={{
                fontSize: 11,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wg-ink-faint)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {f.title}
            </div>
            <div
              style={{
                fontSize: 14,
                lineHeight: 1.55,
                color: "var(--wg-ink)",
              }}
            >
              {f.body}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
