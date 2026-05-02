"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { relativeTime } from "@/components/stream/types";
import { RelTime } from "@/components/stream/RelTime";
import { Button, Card, Heading, Text } from "@/components/ui";

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
    <Card variant="raised" flush>
      <div
        style={{
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {/* Title row */}
        <div>
          <Text
            as="div"
            variant="caption"
            style={{
              color: "var(--wg-ink-faint)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              marginBottom: 4,
            }}
          >
            {active.project_title}
          </Text>
          <Link
            href={`/projects/${active.project_id}`}
            style={{ textDecoration: "none" }}
          >
            <Heading level={2}>{active.task_title}</Heading>
          </Link>
        </div>

        {/* Status + age row */}
        <div
          style={{
            display: "flex",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <Text variant="label" muted style={{ fontFamily: "var(--wg-font-mono)" }}>
            <span style={{ color: "var(--wg-ink-faint)" }}>
              {t("home.active.status")}
            </span>{" "}
            {active.status}
          </Text>
          {active.updated_at ? (
            <Text variant="label" muted style={{ fontFamily: "var(--wg-font-mono)" }}>
              <span style={{ color: "var(--wg-ink-faint)" }}>
                {t("home.active.age")}
              </span>{" "}
              <RelTime iso={active.updated_at} />
            </Text>
          ) : null}
        </div>

        {/* Context triptych */}
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr",
            gap: "6px 16px",
            margin: 0,
          }}
        >
          <Text
            as="dt"
            variant="caption"
            style={{ color: "var(--wg-ink-faint)" }}
          >
            {t("home.active.upstream")}
          </Text>
          <dd style={{ margin: 0, fontSize: "var(--wg-fs-body)" }}>
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
              <Text variant="body" muted>
                —
              </Text>
            )}
          </dd>

          <Text
            as="dt"
            variant="caption"
            style={{ color: "var(--wg-ink-faint)" }}
          >
            {t("home.active.downstream")}
          </Text>
          <dd style={{ margin: 0, fontSize: "var(--wg-fs-body)" }}>
            {active.downstream_task_titles.length === 0 ? (
              <Text variant="body" muted>
                {t("home.active.noDownstream")}
              </Text>
            ) : (
              active.downstream_task_titles.join(" · ")
            )}
          </dd>

          <Text
            as="dt"
            variant="caption"
            style={{ color: "var(--wg-ink-faint)" }}
          >
            {t("home.active.adjacent")}
          </Text>
          <dd style={{ margin: 0, fontSize: "var(--wg-fs-body)" }}>
            {active.adjacent_member_names.length === 0 ? (
              <Text variant="body" muted>
                {t("home.active.noAdjacent")}
              </Text>
            ) : (
              active.adjacent_member_names.join(" · ")
            )}
          </dd>
        </dl>

        <EdgeLLMNudge projectId={active.project_id} />
      </div>
    </Card>
  );
}

function LastDecisionCard({
  active,
}: {
  active: Extract<ActiveContext, { kind: "last_decision" }>;
}) {
  const t = useTranslations();
  return (
    <Card variant="raised" flush>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          padding: 20,
        }}
      >
        {/* relativeTime is interpolated into a translation string here,
            so we can't swap to <RelTime>. suppressHydrationWarning on
            an inner span silences the brief mismatch from server's
            Date.now() differing from client's by ~100ms. */}
        <Text variant="body">
          <span suppressHydrationWarning>
            {t("home.active.lastDecisionFallback", {
              project: active.project_title,
              summary: active.summary,
              time: active.created_at ? relativeTime(active.created_at) : "",
            })}
          </span>
        </Text>
        <Link
          href={`/projects/${active.project_id}/nodes/${active.decision_id}`}
          style={{
            fontSize: "var(--wg-fs-label)",
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
            textDecoration: "none",
          }}
        >
          ⚡ view lineage →
        </Link>
        <EdgeLLMNudge projectId={active.project_id} />
      </div>
    </Card>
  );
}

function CaughtUpCard({
  active,
}: {
  active: Extract<ActiveContext, { kind: "caught_up" }>;
}) {
  const t = useTranslations();
  return (
    <Card variant="raised" flush>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          padding: 20,
        }}
      >
        <Heading level={2}>{t("home.active.caughtUp")}</Heading>
        <Text variant="body" muted>
          <span suppressHydrationWarning>
            {active.last_crystallization_at
              ? t("home.active.caughtUpLastCrystallization", {
                  time: relativeTime(active.last_crystallization_at),
                })
              : t("home.active.caughtUpNoHistory")}
          </span>
        </Text>
      </div>
    </Card>
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
          fontSize: "var(--wg-fs-body)",
          fontFamily: "var(--wg-font-sans)",
          color: "var(--wg-ink)",
        }}
      />
      <Button
        type="submit"
        variant="primary"
        size="md"
        disabled={pending || !text.trim()}
      >
        →
      </Button>
      {error ? (
        <span
          role="alert"
          style={{
            fontSize: "var(--wg-fs-caption)",
            fontFamily: "var(--wg-font-mono)",
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
