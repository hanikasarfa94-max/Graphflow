"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { relativeTime } from "@/components/stream/types";

import type { ActiveContext } from "./data";
import { SectionHeader } from "./SectionHeader";

// Active task / last-decision / caught-up context. Client component
// because the edge-LLM "nudge" input needs state + submit.
export function ActiveSection({ active }: { active: ActiveContext }) {
  const t = useTranslations();

  return (
    <section style={{ marginBottom: 40 }} aria-labelledby="home-active">
      <SectionHeader title={t("home.active.title")} />
      {active.kind === "task" ? (
        <ActiveTaskCard active={active} />
      ) : active.kind === "last_decision" ? (
        <LastDecisionCard active={active} />
      ) : (
        <CaughtUpCard active={active} />
      )}
    </section>
  );
}

function ActiveTaskCard({
  active,
}: {
  active: Extract<ActiveContext, { kind: "task" }>;
}) {
  const t = useTranslations();

  return (
    <div
      style={{
        padding: 20,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface-raised)",
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      {/* Title row */}
      <div>
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            marginBottom: 4,
          }}
        >
          {active.project_title}
        </div>
        <Link
          href={`/projects/${active.project_id}`}
          style={{
            fontSize: 18,
            fontWeight: 600,
            color: "var(--wg-ink)",
            textDecoration: "none",
            lineHeight: 1.3,
          }}
        >
          {active.task_title}
        </Link>
      </div>

      {/* Status + age row */}
      <div
        style={{
          display: "flex",
          gap: 16,
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          flexWrap: "wrap",
        }}
      >
        <span>
          <span style={{ color: "var(--wg-ink-faint)" }}>
            {t("home.active.status")}
          </span>{" "}
          {active.status}
        </span>
        {active.updated_at ? (
          <span>
            <span style={{ color: "var(--wg-ink-faint)" }}>
              {t("home.active.age")}
            </span>{" "}
            {relativeTime(active.updated_at)}
          </span>
        ) : null}
      </div>

      {/* Context triptych */}
      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "6px 16px",
          margin: 0,
          fontSize: 13,
          lineHeight: 1.5,
        }}
      >
        <dt style={{ color: "var(--wg-ink-faint)", fontFamily: "var(--wg-font-mono)", fontSize: 11 }}>
          {t("home.active.upstream")}
        </dt>
        <dd style={{ margin: 0 }}>
          {active.upstream_decision ? (
            <Link
              href={`/projects/${active.project_id}/nodes/${active.upstream_decision.id}`}
              style={{ color: "var(--wg-accent)", textDecoration: "none" }}
            >
              ⚡{" "}
              {active.upstream_decision.rationale ||
                active.upstream_decision.custom_text ||
                "(decision)"}
            </Link>
          ) : (
            <span style={{ color: "var(--wg-ink-faint)" }}>—</span>
          )}
        </dd>

        <dt style={{ color: "var(--wg-ink-faint)", fontFamily: "var(--wg-font-mono)", fontSize: 11 }}>
          {t("home.active.downstream")}
        </dt>
        <dd style={{ margin: 0 }}>
          {active.downstream_task_titles.length === 0 ? (
            <span style={{ color: "var(--wg-ink-faint)" }}>
              {t("home.active.noDownstream")}
            </span>
          ) : (
            active.downstream_task_titles.join(" · ")
          )}
        </dd>

        <dt style={{ color: "var(--wg-ink-faint)", fontFamily: "var(--wg-font-mono)", fontSize: 11 }}>
          {t("home.active.adjacent")}
        </dt>
        <dd style={{ margin: 0 }}>
          {active.adjacent_member_names.length === 0 ? (
            <span style={{ color: "var(--wg-ink-faint)" }}>
              {t("home.active.noAdjacent")}
            </span>
          ) : (
            active.adjacent_member_names.join(" · ")
          )}
        </dd>
      </dl>

      <EdgeLLMNudge projectId={active.project_id} />
    </div>
  );
}

function LastDecisionCard({
  active,
}: {
  active: Extract<ActiveContext, { kind: "last_decision" }>;
}) {
  const t = useTranslations();
  return (
    <div
      style={{
        padding: 20,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface-raised)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div
        style={{
          fontSize: 14,
          lineHeight: 1.5,
          color: "var(--wg-ink)",
        }}
      >
        {t("home.active.lastDecisionFallback", {
          project: active.project_title,
          summary: active.summary,
          time: active.created_at ? relativeTime(active.created_at) : "",
        })}
      </div>
      <Link
        href={`/projects/${active.project_id}/nodes/${active.decision_id}`}
        style={{
          fontSize: 12,
          color: "var(--wg-accent)",
          fontFamily: "var(--wg-font-mono)",
          textDecoration: "none",
        }}
      >
        ⚡ view lineage →
      </Link>
      <EdgeLLMNudge projectId={active.project_id} />
    </div>
  );
}

function CaughtUpCard({
  active,
}: {
  active: Extract<ActiveContext, { kind: "caught_up" }>;
}) {
  const t = useTranslations();
  return (
    <div
      style={{
        padding: 20,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface-raised)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ fontSize: 16, fontWeight: 600 }}>
        {t("home.active.caughtUp")}
      </div>
      <div
        style={{
          fontSize: 13,
          color: "var(--wg-ink-soft)",
        }}
      >
        {active.last_crystallization_at
          ? t("home.active.caughtUpLastCrystallization", {
              time: relativeTime(active.last_crystallization_at),
            })
          : t("home.active.caughtUpNoHistory")}
      </div>
    </div>
  );
}

// Edge-LLM "rehearsal" input. v1: submits as a regular project message
// to the owning project stream. The real rehearsal endpoint is deferred.
// If no project_id, the input is not rendered.
function EdgeLLMNudge({ projectId }: { projectId: string }) {
  const t = useTranslations();
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setError(null);
    setPending(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: text }),
        credentials: "include",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `error ${res.status}`);
        return;
      }
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "network error");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      style={{
        display: "flex",
        gap: 8,
        alignItems: "stretch",
        paddingTop: 12,
        borderTop: "1px dashed var(--wg-line)",
      }}
    >
      <div
        aria-hidden
        style={{
          fontSize: 14,
          alignSelf: "center",
        }}
      >
        💭
      </div>
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("home.active.llmOffer")}
        aria-label={t("home.active.llmSendLabel")}
        style={{
          flex: 1,
          padding: "8px 12px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          background: "var(--wg-surface)",
          fontSize: 13,
          fontFamily: "var(--wg-font-sans)",
          color: "var(--wg-ink)",
        }}
      />
      <button
        type="submit"
        disabled={pending || !text.trim()}
        style={{
          padding: "8px 14px",
          background: "var(--wg-accent)",
          color: "#fff",
          border: "none",
          borderRadius: "var(--wg-radius)",
          fontSize: 12,
          fontWeight: 600,
          cursor: pending ? "progress" : "pointer",
          opacity: pending || !text.trim() ? 0.55 : 1,
        }}
      >
        →
      </button>
      {error ? (
        <span
          role="alert"
          style={{
            fontSize: 11,
            color: "var(--wg-accent)",
            alignSelf: "center",
          }}
        >
          {error}
        </span>
      ) : null}
    </form>
  );
}
