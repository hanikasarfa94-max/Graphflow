import { getTranslations } from "next-intl/server";
import Link from "next/link";

import type { Decision } from "@/lib/api";

import { EmptyState, Panel } from "./Panel";
import { formatIso } from "@/lib/time";

// Newest-first list, capped at 10. "from IM" badge when the decision
// crystallized off an IM suggestion (source_suggestion_id set).
export async function DecisionsPanel({
  decisions,
  projectId,
}: {
  decisions: Decision[];
  projectId: string;
}) {
  const t = await getTranslations();

  const recent = [...decisions]
    .sort((a, b) => {
      const at = a.created_at ? Date.parse(a.created_at) : 0;
      const bt = b.created_at ? Date.parse(b.created_at) : 0;
      return bt - at;
    })
    .slice(0, 10);

  return (
    <Panel
      title={t("status.decisions.title")}
      subtitle={recent.length > 0 ? String(recent.length) : undefined}
    >
      {recent.length === 0 ? (
        <EmptyState>{t("status.decisions.empty")}</EmptyState>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "grid",
            gap: 8,
          }}
        >
          {recent.map((d) => (
            <li
              key={d.id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "10px 12px",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius)",
                background: "var(--wg-surface)",
              }}
            >
              <div
                aria-hidden="true"
                style={{
                  fontSize: 16,
                  color: "var(--wg-accent)",
                  marginTop: 1,
                }}
              >
                ⚡
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--wg-ink)",
                    fontWeight: 500,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {d.rationale || d.custom_text || "—"}
                </div>
                <div
                  style={{
                    marginTop: 4,
                    display: "flex",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: 8,
                    fontSize: 11,
                    fontFamily: "var(--wg-font-mono)",
                    color: "var(--wg-ink-soft)",
                  }}
                >
                  {d.resolver_display_name ? (
                    <span>
                      {t("status.decisions.resolvedBy", {
                        name: d.resolver_display_name,
                      })}
                    </span>
                  ) : null}
                  <span>
                    {d.created_at
                      ? formatIso(d.created_at)
                      : ""}
                  </span>
                  {/* Provenance — show one badge for whichever source
                      origin produced this decision. Order: gated >
                      conflict > IM, since gated proposals subsume the
                      others when present. */}
                  {d.gated_via_proposal_id ? (
                    <span
                      style={{
                        padding: "1px 6px",
                        borderRadius: 10,
                        background: "var(--wg-accent-soft)",
                        border: "1px solid var(--wg-accent)",
                        color: "var(--wg-accent)",
                      }}
                    >
                      {d.decision_class
                        ? t("status.decisions.fromGated", {
                            cls: d.decision_class,
                          })
                        : t("status.decisions.fromGatedShort")}
                    </span>
                  ) : d.conflict_id ? (
                    <span
                      style={{
                        padding: "1px 6px",
                        borderRadius: 10,
                        background: "var(--wg-amber-soft)",
                        border: "1px solid var(--wg-amber, #c58b00)",
                        color: "var(--wg-amber, #c58b00)",
                      }}
                    >
                      {t("status.decisions.fromConflict")}
                    </span>
                  ) : d.source_suggestion_id ? (
                    <span
                      style={{
                        padding: "1px 6px",
                        borderRadius: 10,
                        background: "var(--wg-surface-raised)",
                        border: "1px solid var(--wg-line)",
                        color: "var(--wg-ink-soft)",
                      }}
                    >
                      {t("status.decisions.fromIm")}
                    </span>
                  ) : null}
                  {d.apply_outcome && d.apply_outcome !== "ok" ? (
                    <span
                      title={t("status.decisions.applyOutcomeHint")}
                      style={{
                        padding: "1px 6px",
                        borderRadius: 10,
                        background:
                          d.apply_outcome === "failed"
                            ? "var(--wg-accent-soft)"
                            : "var(--wg-surface-raised)",
                        border: "1px solid var(--wg-line)",
                        color:
                          d.apply_outcome === "failed"
                            ? "var(--wg-accent)"
                            : "var(--wg-ink-soft)",
                      }}
                    >
                      {t(
                        `status.decisions.applyOutcome.${d.apply_outcome}` as never,
                        { fallback: d.apply_outcome } as never,
                      )}
                    </span>
                  ) : null}
                  <Link
                    href={`/projects/${projectId}/nodes/${d.id}`}
                    style={{
                      color: "var(--wg-accent)",
                      textDecoration: "none",
                    }}
                  >
                    {t("status.decisions.viewLineage")} →
                  </Link>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
