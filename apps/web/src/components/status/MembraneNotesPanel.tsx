// MembraneNotesPanel — Batch C surface.
//
// The membrane (MembraneService.review) records two kinds of
// outstanding work the FE didn't surface anywhere prominent before:
//   1. pending_reviews — drafts staged via request_review, queued for
//      an owner to accept (the team-room IMSuggestion(membrane_review))
//   2. pending_clarifications — questions the membrane posted to a
//      proposer's personal stream after request_clarification
//
// Status page section: "Membrane notes". Server component, one fetch
// to /api/projects/{id}/membrane/notes. Empty state means "the
// membrane isn't holding anything for human attention" — that's
// the calm state we want most of the time. The panel is intended
// to be quiet 80% of the time; loud when it has work.

import { getTranslations } from "next-intl/server";

import type { MembraneNotesResponse } from "@/lib/api";

import { EmptyState, Panel } from "./Panel";
import { formatDate } from "@/lib/time";

export async function MembraneNotesPanel({
  projectId,
  notes,
}: {
  projectId: string;
  notes: MembraneNotesResponse | null;
}) {
  const t = await getTranslations("status.membraneNotes");

  const reviews = notes?.pending_reviews ?? [];
  const clarifications = notes?.pending_clarifications ?? [];
  const total = reviews.length + clarifications.length;

  if (total === 0) {
    return (
      <Panel title={t("title")}>
        <EmptyState>{t("empty")}</EmptyState>
      </Panel>
    );
  }

  return (
    <Panel title={t("title")} subtitle={String(total)}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {reviews.length > 0 ? (
          <section>
            <SectionHead label={t("pendingReviews")} count={reviews.length} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {reviews.map((r) => {
                const detail = r.proposal?.detail ?? {};
                const candidateKind = detail.candidate_kind ?? "kb_item_group";
                const linkedId = detail.task_id ?? detail.kb_item_id ?? "";
                return (
                  <NoteRow
                    key={r.id}
                    kindLabel={
                      candidateKind === "task_promote"
                        ? t("kind.taskPromote")
                        : t("kind.kbItemGroup")
                    }
                    title={r.proposal?.summary ?? r.reasoning ?? "(no summary)"}
                    diff={detail.diff_summary ?? null}
                    metaText={linkedId ? `→ ${linkedId.slice(0, 8)}` : null}
                    createdAt={r.created_at}
                    accent="amber"
                  />
                );
              })}
            </div>
          </section>
        ) : null}
        {clarifications.length > 0 ? (
          <section>
            <SectionHead
              label={t("pendingClarifications")}
              count={clarifications.length}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {clarifications.map((c) => {
                // Body is a multi-line string built by notify_clarification;
                // the question itself is usually the first ~200 chars.
                const summary = c.body.split("\n").find((l) => l.trim()) ?? "";
                return (
                  <NoteRow
                    key={c.id}
                    kindLabel={t("kind.clarify")}
                    title={summary.slice(0, 200)}
                    diff={null}
                    metaText={c.linked_id ? `→ ${c.linked_id.slice(0, 8)}` : null}
                    createdAt={c.created_at}
                    accent="accent"
                  />
                );
              })}
            </div>
          </section>
        ) : null}
      </div>
    </Panel>
  );
}

function SectionHead({ label, count }: { label: string; count: number }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        marginBottom: 6,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        color: "var(--wg-ink-soft)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
      }}
    >
      <span>{label}</span>
      <span style={{ color: "var(--wg-ink-faint)" }}>· {count}</span>
    </div>
  );
}

function NoteRow({
  kindLabel,
  title,
  diff,
  metaText,
  createdAt,
  accent,
}: {
  kindLabel: string;
  title: string;
  diff: string | null;
  metaText: string | null;
  createdAt: string | null;
  accent: "amber" | "accent";
}) {
  const accentColor =
    accent === "amber" ? "var(--wg-amber)" : "var(--wg-accent)";
  return (
    <div
      style={{
        padding: "10px 12px",
        background: "var(--wg-surface)",
        border: "1px solid var(--wg-line)",
        borderLeft: `3px solid ${accentColor}`,
        borderRadius: "var(--wg-radius-sm, 4px)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            padding: "1px 8px",
            borderRadius: 999,
            fontSize: 10,
            fontFamily: "var(--wg-font-mono)",
            fontWeight: 600,
            color: accentColor,
            background:
              accent === "amber"
                ? "var(--wg-amber-soft)"
                : "var(--wg-accent-soft)",
          }}
        >
          {kindLabel}
        </span>
        {metaText ? (
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
            }}
          >
            {metaText}
          </span>
        ) : null}
        {createdAt ? (
          <span
            style={{
              marginLeft: "auto",
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
            }}
          >
            {formatDate(createdAt)}
          </span>
        ) : null}
      </div>
      <div
        style={{
          fontSize: 13,
          color: "var(--wg-ink)",
          lineHeight: 1.4,
        }}
      >
        {title}
      </div>
      {diff ? (
        <div
          style={{
            marginTop: 4,
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            lineHeight: 1.4,
            whiteSpace: "pre-wrap",
          }}
        >
          {diff}
        </div>
      ) : null}
    </div>
  );
}
