import type { ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ProjectOverview({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);

  const conflictSummary = state.conflict_summary;
  const openCount = conflictSummary?.open ?? 0;

  return (
    <section style={{ display: "grid", gap: 16 }}>
      {openCount > 0 && (
        <a
          href={`/projects/${id}/conflicts`}
          data-testid="conflict-banner"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "10px 14px",
            background: "#fdecec",
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink)",
            textDecoration: "none",
            fontSize: 14,
          }}
        >
          <span
            style={{
              background: "var(--wg-accent)",
              color: "#fff",
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 10,
            }}
          >
            {openCount}
          </span>
          <span>
            <strong>
              {openCount === 1 ? "conflict" : "conflicts"} need attention
            </strong>
            <span
              style={{
                marginLeft: 8,
                color: "var(--wg-ink-soft)",
                fontFamily: "var(--wg-font-mono)",
                fontSize: 12,
              }}
            >
              {severityChip(conflictSummary)}
            </span>
          </span>
          <span
            style={{
              marginLeft: "auto",
              color: "var(--wg-ink-soft)",
              fontFamily: "var(--wg-font-mono)",
              fontSize: 12,
            }}
          >
            review →
          </span>
        </a>
      )}

      <Card title="Members">
        <ul style={listStyle}>
          {state.members.map((m) => (
            <li key={m.user_id} style={rowStyle}>
              <span>
                {m.display_name}{" "}
                <span
                  style={{
                    fontFamily: "var(--wg-font-mono)",
                    color: "var(--wg-ink-soft)",
                    fontSize: 12,
                  }}
                >
                  @{m.username}
                </span>
              </span>
              <span style={mutedMono}>{m.role}</span>
            </li>
          ))}
          {state.members.length === 0 && <li style={emptyStyle}>none yet</li>}
        </ul>
      </Card>

      <Card title="Deliverables">
        <ul style={listStyle}>
          {state.graph.deliverables.map((d) => (
            <li key={d.id} style={rowStyle}>
              <span>{d.title}</span>
              <span style={mutedMono}>
                {(d.kind ?? "") as string}
                {d.status ? ` · ${d.status}` : ""}
              </span>
            </li>
          ))}
          {state.graph.deliverables.length === 0 && (
            <li style={emptyStyle}>waiting for requirements parse</li>
          )}
        </ul>
      </Card>

      <Card title="Risks">
        <ul style={listStyle}>
          {state.graph.risks.map((r) => (
            <li key={r.id} style={rowStyle}>
              <span>{r.title}</span>
              <span style={mutedMono}>
                {r.severity} · {r.status}
              </span>
            </li>
          ))}
          {state.graph.risks.length === 0 && (
            <li style={emptyStyle}>no open risks</li>
          )}
        </ul>
      </Card>
    </section>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        padding: 16,
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      <h2
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wg-ink-soft)",
          margin: "0 0 10px",
        }}
      >
        {title}
      </h2>
      {children}
    </div>
  );
}

const listStyle: React.CSSProperties = {
  listStyle: "none",
  padding: 0,
  margin: 0,
  display: "grid",
  gap: 6,
};
const rowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  padding: "6px 0",
  borderBottom: "1px dashed var(--wg-line)",
  fontSize: 14,
};
const mutedMono: React.CSSProperties = {
  fontFamily: "var(--wg-font-mono)",
  fontSize: 12,
  color: "var(--wg-ink-soft)",
};
const emptyStyle: React.CSSProperties = {
  fontSize: 13,
  color: "var(--wg-ink-soft)",
  fontStyle: "italic",
};

function severityChip(
  s: { critical: number; high: number; medium: number; low: number } | null | undefined,
): string {
  if (!s) return "";
  const parts: string[] = [];
  if (s.critical) parts.push(`${s.critical} critical`);
  if (s.high) parts.push(`${s.high} high`);
  if (s.medium) parts.push(`${s.medium} medium`);
  if (s.low) parts.push(`${s.low} low`);
  return parts.join(" · ");
}
