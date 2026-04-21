import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

// /projects/[id]/team/perf — observable performance management (§10.5).
//
// Project-admin view only. Access is gated server-side (role === 'owner'
// AND license_tier === 'full'); a 403 renders inline instead of
// redirecting so the caller keeps context. Counts are computed on read
// from the graph — no denormalized columns, no cache.
//
// Visual style mirrors /settings/profile: single-column page, surface
// cards with border + accent, mono numbers. One row per member; clicking
// a count deep-links to the first referenced node (simpler than a
// popover per the task brief).

export const dynamic = "force-dynamic";

interface PerfMetric {
  count: number;
  ids: string[];
}

interface PerfRecord {
  user_id: string;
  display_name: string;
  username: string;
  role_in_project: string;
  license_tier: string;
  decisions_made: PerfMetric;
  routings_answered: PerfMetric;
  risks_owned: PerfMetric;
  tasks_completed: PerfMetric;
  skills_validated: {
    declared: number;
    observed: number;
    overlap: number;
  };
  dissent_accuracy: {
    total: number;
    supported: number;
    refuted: number;
    still_open: number;
  };
  activity_last_30d: {
    messages: number;
    last_active_at: string | null;
  };
}

export default async function ProjectTeamPerfPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}/team/perf`);
  const t = await getTranslations("teamPerf");

  let rows: PerfRecord[] | null = null;
  let forbidden = false;
  try {
    rows = await serverFetch<PerfRecord[]>(
      `/api/projects/${id}/team/perf`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      forbidden = true;
    } else {
      rows = null;
    }
  }

  return (
    <main
      style={{
        maxWidth: 1060,
        margin: "0 auto",
        padding: "32px 24px 80px",
        fontFamily: "var(--wg-font-sans)",
      }}
    >
      <div style={{ marginBottom: 14 }}>
        <Link
          href={`/projects/${id}/team`}
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            textDecoration: "none",
          }}
        >
          ← {t("backToTeam")}
        </Link>
      </div>
      <header style={{ marginBottom: 22 }}>
        <h1
          style={{
            margin: 0,
            fontSize: 28,
            fontWeight: 600,
            color: "var(--wg-ink)",
          }}
        >
          {t("title")}
        </h1>
        <p
          style={{
            margin: "8px 0 0",
            color: "var(--wg-ink-soft)",
            fontSize: 14,
            lineHeight: 1.55,
            maxWidth: 640,
          }}
        >
          {t("subtitle")}
        </p>
      </header>

      {forbidden ? (
        <InlineNotice tone="warn" label={t("forbidden")} />
      ) : rows === null ? (
        <InlineNotice tone="muted" label={t("unavailable")} />
      ) : rows.length === 0 ? (
        <InlineNotice tone="muted" label={t("empty")} />
      ) : (
        <PerfTable projectId={id} rows={rows} t={t} />
      )}
    </main>
  );
}

function InlineNotice({
  tone,
  label,
}: {
  tone: "warn" | "muted";
  label: string;
}) {
  const styles =
    tone === "warn"
      ? {
          background: "var(--wg-amber-soft)",
          border: "1px solid var(--wg-amber)",
          color: "var(--wg-ink)",
        }
      : {
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          color: "var(--wg-ink-soft)",
        };
  return (
    <div
      role="status"
      style={{
        marginTop: 8,
        padding: "12px 16px",
        borderRadius: "var(--wg-radius)",
        fontSize: 13,
        fontFamily: "var(--wg-font-mono)",
        ...styles,
      }}
    >
      {label}
    </div>
  );
}

function PerfTable({
  projectId,
  rows,
  t,
}: {
  projectId: string;
  rows: PerfRecord[];
  t: (k: string) => string;
}) {
  return (
    <section
      style={{
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        overflow: "hidden",
      }}
    >
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 13,
        }}
      >
        <thead>
          <tr
            style={{
              background: "var(--wg-surface)",
              borderBottom: "1px solid var(--wg-line)",
            }}
          >
            <Th>{t("cols.member")}</Th>
            <Th align="right">{t("cols.decisions")}</Th>
            <Th align="right">{t("cols.routings")}</Th>
            <Th align="right">{t("cols.risks")}</Th>
            <Th align="right">{t("cols.tasksDone")}</Th>
            <Th>{t("cols.skills")}</Th>
            <Th>{t("cols.dissentAccuracy")}</Th>
            <Th>{t("cols.activity30d")}</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={row.user_id}
              style={{
                background:
                  idx % 2 === 0
                    ? "transparent"
                    : "var(--wg-line-soft, rgba(0,0,0,0.02))",
                borderBottom:
                  idx === rows.length - 1
                    ? "none"
                    : "1px solid var(--wg-line-soft, var(--wg-line))",
              }}
            >
              <Td>
                <div style={{ fontWeight: 500, color: "var(--wg-ink)" }}>
                  {row.display_name}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    fontFamily: "var(--wg-font-mono)",
                    color: "var(--wg-ink-faint)",
                    marginTop: 2,
                  }}
                >
                  {row.username} · {row.role_in_project} · {row.license_tier}
                </div>
              </Td>
              <Td align="right">
                <CountCell
                  count={row.decisions_made.count}
                  href={deepLink(projectId, "decision", row.decisions_made.ids)}
                />
              </Td>
              <Td align="right">
                <CountCell
                  count={row.routings_answered.count}
                  href={deepLink(projectId, "routing", row.routings_answered.ids)}
                />
              </Td>
              <Td align="right">
                <CountCell
                  count={row.risks_owned.count}
                  href={deepLink(projectId, "risk", row.risks_owned.ids)}
                />
              </Td>
              <Td align="right">
                <CountCell
                  count={row.tasks_completed.count}
                  href={deepLink(projectId, "task", row.tasks_completed.ids)}
                />
              </Td>
              <Td>
                <span
                  style={{
                    fontFamily: "var(--wg-font-mono)",
                    fontSize: 12,
                    color: "var(--wg-ink)",
                  }}
                >
                  {row.skills_validated.declared} / {row.skills_validated.observed} /{" "}
                  {row.skills_validated.overlap}
                </span>
              </Td>
              <Td>
                <DissentCell bucket={row.dissent_accuracy} />
              </Td>
              <Td>
                <div
                  style={{
                    fontFamily: "var(--wg-font-mono)",
                    fontSize: 12,
                    color: "var(--wg-ink)",
                  }}
                >
                  {row.activity_last_30d.messages}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--wg-ink-faint)",
                    marginTop: 2,
                  }}
                >
                  {formatLastActive(row.activity_last_30d.last_active_at, t)}
                </div>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      style={{
        padding: "10px 14px",
        textAlign: align,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        color: "var(--wg-ink-faint)",
        fontWeight: 500,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <td
      style={{
        padding: "12px 14px",
        textAlign: align,
        verticalAlign: "top",
      }}
    >
      {children}
    </td>
  );
}

function DissentCell({
  bucket,
}: {
  bucket: PerfRecord["dissent_accuracy"];
}) {
  // Render {supported}/{total} + a narrow horizontal bar split into
  // three segments (supported green / refuted amber / still_open gray).
  // When total is zero we draw an empty dimmed bar so the column
  // stays visually stable.
  const { total, supported, refuted, still_open } = bucket;
  const pctSupp = total > 0 ? (supported / total) * 100 : 0;
  const pctRef = total > 0 ? (refuted / total) * 100 : 0;
  const pctOpen = total > 0 ? (still_open / total) * 100 : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 80 }}>
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
          color: total === 0 ? "var(--wg-ink-faint)" : "var(--wg-ink)",
        }}
      >
        {supported} / {total}
      </div>
      <div
        style={{
          display: "flex",
          width: 80,
          height: 4,
          background: "var(--wg-line-soft, rgba(0,0,0,0.06))",
          borderRadius: 2,
          overflow: "hidden",
        }}
        aria-hidden
      >
        {total > 0 ? (
          <>
            <span
              style={{
                width: `${pctSupp}%`,
                background: "var(--wg-green, #1f7a3d)",
              }}
            />
            <span
              style={{
                width: `${pctRef}%`,
                background: "var(--wg-amber, #c58b00)",
              }}
            />
            <span
              style={{
                width: `${pctOpen}%`,
                background: "var(--wg-ink-faint)",
                opacity: 0.4,
              }}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}

function CountCell({ count, href }: { count: number; href: string | null }) {
  const content = (
    <span
      style={{
        fontFamily: "var(--wg-font-mono)",
        fontSize: 16,
        fontWeight: 600,
        color: count === 0 ? "var(--wg-ink-faint)" : "var(--wg-accent)",
      }}
    >
      {count}
    </span>
  );
  if (!href || count === 0) return content;
  return (
    <Link href={href} style={{ textDecoration: "none" }}>
      {content}
    </Link>
  );
}

// Best-effort deep-link for a count. Decisions + risks + tasks are
// surfaced in the Audit drawer; routings live under the routing
// drawer. These routes are the canonical surfaces in v1 — if the
// kind isn't routable we return null and render a plain number.
function deepLink(
  projectId: string,
  kind: "decision" | "routing" | "risk" | "task",
  ids: string[],
): string | null {
  if (ids.length === 0) return null;
  const first = ids[0];
  if (kind === "decision") {
    return `/projects/${projectId}/detail/conflicts#decision-${first}`;
  }
  if (kind === "risk") {
    return `/projects/${projectId}/detail/graph#risk-${first}`;
  }
  if (kind === "task") {
    return `/projects/${projectId}/detail/plan#task-${first}`;
  }
  if (kind === "routing") {
    return `/projects/${projectId}/detail/im#routing-${first}`;
  }
  return null;
}

function formatLastActive(
  iso: string | null,
  t: (k: string) => string,
): string {
  if (!iso) return t("lastActiveNever");
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
