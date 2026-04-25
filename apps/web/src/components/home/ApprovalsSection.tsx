import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { EmptyState, Text } from "@/components/ui";
import type { GatedProposal } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

import type { HomeProjectCard } from "./data";
import { SectionHeader } from "./SectionHeader";

// Pulls /api/gated-proposals/pending — proposals where the viewer is the
// named gate-keeper and status is still 'pending'. Renders a row per
// proposal that links to /projects/{id}/status, where the gated card
// already exposes approve / open-to-vote / deny.
export async function ApprovalsSection({
  projects,
}: {
  projects: HomeProjectCard[];
}) {
  const t = await getTranslations();

  let proposals: GatedProposal[] = [];
  try {
    const r = await serverFetch<{ ok: boolean; proposals: GatedProposal[] }>(
      `/api/gated-proposals/pending`,
    );
    proposals = r.proposals ?? [];
  } catch {
    // Treat fetch failures as "nothing pending" so a flaky backend never
    // blocks the rest of the home page from rendering.
    proposals = [];
  }

  if (proposals.length === 0) {
    return null;
  }

  const projectTitleById = new Map(projects.map((p) => [p.id, p.title]));

  return (
    <section style={{ marginBottom: 40 }} aria-labelledby="home-approvals">
      <SectionHeader
        title={t("home.approvals.title")}
        right={
          <Text variant="caption" muted>
            {t("home.approvals.countSubtitle", { count: proposals.length })}
          </Text>
        }
      />
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {proposals.map((p) => (
          <li key={p.id}>
            <ApprovalRow
              proposal={p}
              projectTitle={
                projectTitleById.get(p.project_id) ??
                t("home.approvals.unknownProject")
              }
              reviewLabel={t("home.approvals.review")}
              classLabel={t(
                `home.approvals.class.${p.decision_class}` as never,
                { fallback: p.decision_class } as never,
              )}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

function ApprovalRow({
  proposal,
  projectTitle,
  reviewLabel,
  classLabel,
}: {
  proposal: GatedProposal;
  projectTitle: string;
  reviewLabel: string;
  classLabel: string;
}) {
  const headline =
    proposal.decision_text?.trim() ||
    proposal.proposal_body?.trim() ||
    "(no description)";
  return (
    <Link
      href={`/projects/${proposal.project_id}/status`}
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        alignItems: "center",
        gap: 12,
        padding: "12px 14px",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        textDecoration: "none",
        color: "var(--wg-ink)",
        background: "var(--wg-surface-raised)",
      }}
    >
      <span
        data-decision-class={proposal.decision_class}
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "2px 6px",
          borderRadius: 4,
          background: "var(--wg-accent-soft)",
          color: "var(--wg-accent)",
          border: "1px solid var(--wg-accent)",
          whiteSpace: "nowrap",
        }}
      >
        {classLabel}
      </span>
      <div style={{ minWidth: 0 }}>
        <Text
          as="div"
          variant="body"
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {headline}
        </Text>
        <Text
          as="div"
          variant="caption"
          muted
          style={{ marginTop: 2, color: "var(--wg-ink-faint)" }}
        >
          {projectTitle}
        </Text>
      </div>
      <Text
        variant="caption"
        style={{
          color: "var(--wg-accent)",
          whiteSpace: "nowrap",
        }}
      >
        {reviewLabel}
      </Text>
    </Link>
  );
}
