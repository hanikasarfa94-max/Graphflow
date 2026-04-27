import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { MemberHandoffButton } from "@/components/skills/MemberHandoffButton";
import { PageHeader } from "@/components/ui";
import { serverFetch } from "@/lib/auth";
import type {
  HandoffListPayload,
  SkillAtlasPayload,
  SuccessorInheritedPayload,
} from "@/lib/api";

// /projects/[id]/skills — the group's capability atlas.
//
// Two skills locked to each member:
//   * role skill — imposed by role (derived from role_hints via the
//     server's ROLE_SKILL_BUNDLES). Stays with the role on handoff.
//   * profile skill — declared by the member + validated over time by
//     observed emissions. Stays with the person; non-PII routines pass
//     to successors.
//
// Visibility (per product spec):
//   * owner — sees every member card + collective aggregate
//   * non-owner — sees only their own card; a "restricted view" banner
//     above the grid explains why
//
// Distinct from /settings/profile, which is the user's *personal* view
// of their observed emissions. The atlas is the GROUP-level view.

export const dynamic = "force-dynamic";

export default async function SkillsAtlasPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: projectId } = await params;
  const t = await getTranslations("skillAtlas");

  let payload: SkillAtlasPayload | null = null;
  try {
    payload = await serverFetch<SkillAtlasPayload>(
      `/api/projects/${projectId}/skills`,
    );
  } catch {
    payload = null;
  }

  if (!payload) {
    return (
      <Unavailable projectId={projectId} label={t("unavailable")} />
    );
  }

  const isOwner = payload.viewer_scope === "owner";
  const memberCount = payload.members.length;

  // Polish: surface Stage 3 handoff artifacts on this page.
  //   * Owners see the full handoff history (draft + finalized).
  //   * Non-owners (self view) see what routines they themselves have
  //     inherited as a successor on this project. "Nothing yet" is a
  //     legitimate and common state.
  const [handoffList, inherited] = await Promise.all([
    isOwner
      ? serverFetch<HandoffListPayload>(
          `/api/projects/${projectId}/handoffs`,
        ).catch<HandoffListPayload | null>(() => null)
      : Promise.resolve<HandoffListPayload | null>(null),
    !isOwner && payload.members[0]
      ? serverFetch<SuccessorInheritedPayload>(
          `/api/projects/${projectId}/handoffs/for/${payload.members[0].user_id}`,
        ).catch<SuccessorInheritedPayload | null>(() => null)
      : Promise.resolve<SuccessorInheritedPayload | null>(null),
  ]);

  return (
    <main
      style={{
        maxWidth: 1060,
        margin: "0 auto",
        padding: "40px 24px 80px",
        fontFamily: "var(--wg-font-sans)",
      }}
    >
      <BackStrip projectId={projectId} label={t("backToProject")} />
      <Header
        title={t("title")}
        subtitle={t("subtitle")}
        scopeLabel={
          isOwner
            ? t("scope.ownerView", { count: memberCount })
            : t("scope.selfView")
        }
      />

      {!isOwner ? (
        <div
          role="status"
          style={{
            marginBottom: 20,
            padding: "10px 14px",
            background: "var(--wg-amber-soft)",
            border: "1px solid var(--wg-amber)",
            borderRadius: 4,
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink)",
          }}
        >
          {t("restrictedBanner")}
        </div>
      ) : null}

      {isOwner ? <CollectiveBlock payload={payload} t={t} /> : null}
      {isOwner ? <TeamShapeBlock payload={payload} t={t} /> : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 18,
          marginTop: 22,
        }}
      >
        {payload.members.map((m) => (
          <MemberCard
            key={m.user_id}
            card={m}
            t={t}
            projectId={projectId}
            isOwnerView={isOwner}
            allMembers={payload.members}
          />
        ))}
      </div>

      {isOwner && handoffList ? (
        <HandoffHistoryBlock list={handoffList} t={t} />
      ) : null}

      {!isOwner && inherited && inherited.inherited_routines.length > 0 ? (
        <InheritedBlock payload={inherited} t={t} />
      ) : null}
    </main>
  );
}

// ---- Pieces ---------------------------------------------------------------

function Unavailable({
  projectId,
  label,
}: {
  projectId: string;
  label: string;
}) {
  return (
    <main
      style={{
        maxWidth: 640,
        margin: "0 auto",
        padding: "80px 24px",
        textAlign: "center",
      }}
    >
      <p style={{ color: "var(--wg-ink-faint)", fontSize: 14, marginBottom: 20 }}>
        {label}
      </p>
      <Link
        href={`/projects/${projectId}`}
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-accent)",
        }}
      >
        ← {projectId.slice(0, 8)}
      </Link>
    </main>
  );
}

function BackStrip({
  projectId,
  label,
}: {
  projectId: string;
  label: string;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <Link
        href={`/projects/${projectId}`}
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          textDecoration: "none",
        }}
      >
        ← {label}
      </Link>
    </div>
  );
}

function Header({
  title,
  subtitle,
  scopeLabel,
}: {
  title: string;
  subtitle: string;
  scopeLabel: string;
}) {
  return (
    <PageHeader
      title={title}
      subtitle={subtitle}
      right={
        <span
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          {scopeLabel}
        </span>
      }
    />
  );
}

function CollectiveBlock({
  payload,
  t,
}: {
  payload: SkillAtlasPayload;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const c = payload.collective;
  if (!c || Object.keys(c).length === 0) return null;
  return (
    <section
      style={{
        marginBottom: 22,
        padding: "16px 20px",
        background: "var(--wg-accent-soft)",
        border: "1px solid var(--wg-accent-ring)",
        borderRadius: "var(--wg-radius-md)",
      }}
    >
      <h2
        style={{
          margin: "0 0 10px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--wg-accent)",
        }}
      >
        {t("collective.title")}
      </h2>
      <CollectiveRow
        label={t("collective.roleSkillCoverage")}
        skills={c.role_skill_coverage ?? []}
      />
      <CollectiveRow
        label={t("collective.declaredCombined")}
        skills={c.declared_abilities_combined ?? []}
      />
      <CollectiveRow
        label={t("collective.observedCombined")}
        skills={c.observed_skills_combined ?? []}
      />
      <CollectiveRow
        label={t("collective.unvalidated")}
        skills={c.unvalidated_declarations ?? []}
        tone="gap"
        emptyLabel={t("collective.noGaps")}
      />
    </section>
  );
}

// Phase S — "how does this team think" summary. Observed governance
// + activity in the last 30d, rolled up across all members. Owner-
// only block, sits below the skill collective. Read-only; the
// actual org-composition tool (drag-rebalance, SPOF flags) lives on
// the /composition route.
function TeamShapeBlock({
  payload,
  t,
}: {
  payload: SkillAtlasPayload;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const ts = payload.team_shape;
  if (!ts || Object.keys(ts).length === 0) return null;

  const memberCount = ts.member_count ?? 0;
  const totalVotes = ts.total_votes_30d ?? 0;
  const totalDecisions = ts.total_decisions_30d ?? 0;
  const voteParticipation = Math.round((ts.vote_participation_ratio ?? 0) * 100);
  const decisionParticipation = Math.round(
    (ts.decision_participation_ratio ?? 0) * 100,
  );
  const dissentMix = Math.round((ts.dissent_mix ?? 0) * 100);
  const concentration = Math.round((ts.decision_concentration ?? 0) * 100);

  // Character signal: we translate the numeric rollup into one-word
  // characterizations the owner can read at a glance. These aren't
  // measurements — they're hints ("high dissent" vs "rubber-stamp").
  // Rules:
  //   dissent_mix >= 0.35 → "deliberative"; <0.10 → "consensus-heavy"; else "balanced"
  //   decision_concentration >= 0.6 → "concentrated"; <=0.2 → "distributed"; else "moderate"
  //   vote_participation_ratio >= 0.8 → "engaged"; <=0.3 → "quiet"; else "mixed"
  const dissentShape =
    (ts.dissent_mix ?? 0) >= 0.35
      ? "deliberative"
      : (ts.dissent_mix ?? 0) < 0.1 && totalVotes > 0
        ? "consensusHeavy"
        : "balanced";
  const concentrationShape =
    (ts.decision_concentration ?? 0) >= 0.6
      ? "concentrated"
      : (ts.decision_concentration ?? 0) <= 0.2
        ? "distributed"
        : "moderate";
  const engagementShape =
    (ts.vote_participation_ratio ?? 0) >= 0.8
      ? "engaged"
      : (ts.vote_participation_ratio ?? 0) <= 0.3
        ? "quiet"
        : "mixed";

  return (
    <section
      data-testid="team-shape-block"
      style={{
        marginBottom: 22,
        padding: "16px 20px",
        background: "var(--wg-surface-sunk, var(--wg-surface))",
        border: "1px solid var(--wg-line)",
        borderLeft: "3px solid var(--wg-ok)",
        borderRadius: "var(--wg-radius-md)",
      }}
    >
      <h2
        style={{
          margin: "0 0 6px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--wg-ok)",
        }}
      >
        {t("teamShape.title")}
      </h2>
      <div
        style={{
          fontSize: 13,
          color: "var(--wg-ink-soft)",
          marginBottom: 14,
        }}
      >
        {t("teamShape.subtitle", { member_count: memberCount })}
      </div>

      {/* Character chips — the one-glance read */}
      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          marginBottom: 16,
        }}
      >
        <ShapeChip label={t(`teamShape.engagement.${engagementShape}`)} />
        <ShapeChip label={t(`teamShape.concentration.${concentrationShape}`)} />
        {totalVotes > 0 ? (
          <ShapeChip label={t(`teamShape.dissent.${dissentShape}`)} />
        ) : null}
      </div>

      {/* Numeric summary — 4 metrics in a tight grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
        }}
      >
        <Metric
          label={t("teamShape.votes30d")}
          value={`${totalVotes}`}
          caption={t("teamShape.activeVoters", {
            n: ts.active_voters_30d ?? 0,
            pct: voteParticipation,
          })}
        />
        <Metric
          label={t("teamShape.decisions30d")}
          value={`${totalDecisions}`}
          caption={t("teamShape.activeDeciders", {
            n: ts.active_deciders_30d ?? 0,
            pct: decisionParticipation,
          })}
        />
        <Metric
          label={t("teamShape.dissentMix")}
          value={`${dissentMix}%`}
          caption={t("teamShape.dissentHint")}
        />
        <Metric
          label={t("teamShape.concentration30d")}
          value={`${concentration}%`}
          caption={t("teamShape.concentrationHint")}
        />
      </div>
    </section>
  );
}

function ShapeChip({ label }: { label: string }) {
  return (
    <span
      style={{
        padding: "3px 10px",
        background: "var(--wg-ok-soft, var(--wg-surface-raised))",
        border: "1px solid var(--wg-ok)",
        color: "var(--wg-ok)",
        borderRadius: 999,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        fontWeight: 600,
        textTransform: "lowercase",
        letterSpacing: "0.02em",
      }}
    >
      {label}
    </span>
  );
}

function Metric({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <div
      style={{
        padding: "10px 12px",
        background: "var(--wg-surface-raised, var(--wg-surface))",
        border: "1px solid var(--wg-line-soft, var(--wg-line))",
        borderRadius: "var(--wg-radius-sm, 4px)",
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: "var(--wg-ink)",
          fontFamily: "var(--wg-font-sans)",
          lineHeight: 1.1,
          marginBottom: 4,
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          lineHeight: 1.3,
        }}
      >
        {caption}
      </div>
    </div>
  );
}

function CollectiveRow({
  label,
  skills,
  tone,
  emptyLabel,
}: {
  label: string;
  skills: string[];
  tone?: "gap";
  emptyLabel?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 14,
        padding: "6px 0",
        borderBottom: "1px solid var(--wg-line-soft)",
      }}
    >
      <div
        style={{
          width: 180,
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          paddingTop: 4,
        }}
      >
        {label}
      </div>
      <div style={{ flex: 1, display: "flex", flexWrap: "wrap", gap: 6 }}>
        {skills.length > 0 ? (
          skills.map((s) => <SkillChip key={s} label={s} tone={tone} />)
        ) : (
          <em style={{ fontSize: 12, color: "var(--wg-ink-faint)" }}>
            {emptyLabel ?? "—"}
          </em>
        )}
      </div>
    </div>
  );
}

function MemberCard({
  card,
  t,
  projectId,
  isOwnerView,
  allMembers,
}: {
  card: SkillAtlasPayload["members"][number];
  t: (key: string, values?: Record<string, string | number>) => string;
  projectId: string;
  isOwnerView: boolean;
  allMembers: SkillAtlasPayload["members"];
}) {
  return (
    <article
      style={{
        padding: 18,
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-md)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <header>
        <div
          style={{
            fontSize: 16,
            fontWeight: 600,
            color: "var(--wg-ink)",
          }}
        >
          {card.display_name}
        </div>
        <div
          style={{
            marginTop: 2,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
          }}
        >
          {card.username} · {card.project_role}
          {card.role_hints.length > 0
            ? ` · ${card.role_hints.join(", ")}`
            : ""}
        </div>
      </header>

      <SkillSection
        title={t("card.roleSkills")}
        subtitle={t("card.roleSkillsSubtitle")}
        skills={card.role_skills}
        emptyLabel={t("card.noRoleSkills")}
      />

      <SkillSection
        title={t("card.declaredAbilities")}
        subtitle={t("card.declaredSubtitle")}
        skills={card.profile_skills_declared}
        emptyLabel={t("card.noDeclared")}
        validated={new Set(card.profile_skills_validated)}
      />

      <SkillSection
        title={t("card.observedSkills")}
        subtitle={t("card.observedSubtitle")}
        skills={card.profile_skills_observed}
        emptyLabel={t("card.noObserved")}
        tone="observed"
      />

      <footer
        style={{
          marginTop: 4,
          paddingTop: 10,
          borderTop: "1px solid var(--wg-line-soft)",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          display: "flex",
          gap: 14,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <span>{t("card.messagesTag", { n: card.observed_tallies.messages_posted_30d ?? 0 })}</span>
        <span>{t("card.decisionsTag", { n: card.observed_tallies.decisions_resolved_30d ?? 0 })}</span>
        <span>{t("card.risksTag", { n: card.observed_tallies.risks_owned ?? 0 })}</span>
        {isOwnerView ? (
          <div style={{ marginLeft: "auto" }}>
            <MemberHandoffButton
              projectId={projectId}
              departingMember={card}
              candidates={allMembers}
            />
          </div>
        ) : null}
      </footer>
    </article>
  );
}

function SkillSection({
  title,
  subtitle,
  skills,
  emptyLabel,
  validated,
  tone,
}: {
  title: string;
  subtitle?: string;
  skills: string[];
  emptyLabel: string;
  validated?: Set<string>;
  tone?: "observed";
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          marginBottom: 4,
        }}
      >
        {title}
      </div>
      {subtitle ? (
        <div
          style={{
            fontSize: 11,
            color: "var(--wg-ink-faint)",
            marginBottom: 6,
            fontStyle: "italic",
          }}
        >
          {subtitle}
        </div>
      ) : null}
      {skills.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {skills.map((s) => {
            const isValidated = validated?.has(s.toLowerCase()) ?? false;
            return (
              <SkillChip
                key={s}
                label={s}
                tone={
                  tone === "observed"
                    ? "observed"
                    : isValidated
                      ? "validated"
                      : undefined
                }
              />
            );
          })}
        </div>
      ) : (
        <em style={{ fontSize: 12, color: "var(--wg-ink-faint)" }}>
          {emptyLabel}
        </em>
      )}
    </div>
  );
}

function HandoffHistoryBlock({
  list,
  t,
}: {
  list: HandoffListPayload;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const rows = list.handoffs;
  return (
    <section
      style={{
        marginTop: 32,
        padding: "16px 20px",
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-md)",
      }}
    >
      <h2
        style={{
          margin: "0 0 10px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--wg-ink-faint)",
        }}
      >
        {t("handoff.existingHeader")}
      </h2>
      {rows.length === 0 ? (
        <em
          style={{
            fontSize: 12,
            color: "var(--wg-ink-faint)",
          }}
        >
          {t("handoff.noExisting")}
        </em>
      ) : (
        <ul
          style={{
            margin: 0,
            padding: 0,
            listStyle: "none",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {rows.map((h) => (
            <li
              key={h.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "8px 12px",
                background: "var(--wg-surface)",
                border: "1px solid var(--wg-line-soft, var(--wg-line))",
                borderRadius: 6,
                fontSize: 13,
                gap: 10,
                flexWrap: "wrap",
              }}
            >
              <div>
                <strong>{h.from_display_name}</strong>
                <span style={{ color: "var(--wg-ink-soft)", margin: "0 8px" }}>
                  →
                </span>
                <strong>{h.to_display_name}</strong>
                <span
                  style={{
                    marginLeft: 10,
                    fontFamily: "var(--wg-font-mono)",
                    fontSize: 11,
                    color: "var(--wg-ink-faint)",
                  }}
                >
                  · {h.role_skills_transferred.length} role ·{" "}
                  {h.profile_skill_routines.length} routines
                </span>
              </div>
              <span
                style={{
                  padding: "2px 8px",
                  background:
                    h.status === "finalized"
                      ? "rgba(22, 163, 74,0.15)"
                      : "var(--wg-amber-soft)",
                  color:
                    h.status === "finalized"
                      ? "var(--wg-ok, #2f8f4f)"
                      : "var(--wg-amber)",
                  border: `1px solid ${
                    h.status === "finalized"
                      ? "var(--wg-ok, #2f8f4f)"
                      : "var(--wg-amber)"
                  }`,
                  borderRadius: 12,
                  fontSize: 10,
                  fontFamily: "var(--wg-font-mono)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                {h.status === "finalized"
                  ? t("handoff.statusFinalized")
                  : t("handoff.statusDraft")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function InheritedBlock({
  payload,
  t,
}: {
  payload: SuccessorInheritedPayload;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <section
      style={{
        marginTop: 32,
        padding: "16px 20px",
        background: "var(--wg-accent-soft)",
        border: "1px solid var(--wg-accent-ring, var(--wg-accent))",
        borderRadius: "var(--wg-radius-md)",
      }}
    >
      <h2
        style={{
          margin: "0 0 6px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--wg-accent)",
        }}
      >
        {t("inherited.header")}
      </h2>
      <p
        style={{
          margin: "0 0 10px",
          fontSize: 12,
          color: "var(--wg-ink-soft)",
          lineHeight: 1.55,
        }}
      >
        {t("inherited.subtitle", {
          count: payload.predecessors.length,
        })}
      </p>
      {payload.inherited_role_skills.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 10 }}>
          {payload.inherited_role_skills.map((s) => (
            <SkillChip key={`role-${s}`} label={s} />
          ))}
        </div>
      ) : null}
      <ul
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {payload.inherited_routines.map((r) => (
          <li
            key={r.skill}
            style={{
              padding: "6px 10px",
              background: "var(--wg-surface)",
              border: "1px solid var(--wg-line-soft, var(--wg-line))",
              borderRadius: 6,
              fontSize: 12,
              color: "var(--wg-ink-soft)",
            }}
          >
            <code
              style={{
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-accent)",
                marginRight: 8,
              }}
            >
              {r.skill}
            </code>
            {r.summary}
          </li>
        ))}
      </ul>
    </section>
  );
}

function SkillChip({
  label,
  tone,
}: {
  label: string;
  tone?: "observed" | "validated" | "gap";
}) {
  const styles: Record<string, { bg: string; fg: string; border: string }> = {
    observed: {
      bg: "rgba(22, 163, 74,0.1)",
      fg: "var(--wg-ok)",
      border: "var(--wg-ok)",
    },
    validated: {
      bg: "rgba(22, 163, 74,0.18)",
      fg: "var(--wg-ok)",
      border: "var(--wg-ok)",
    },
    gap: {
      bg: "var(--wg-amber-soft)",
      fg: "var(--wg-amber)",
      border: "var(--wg-amber)",
    },
    default: {
      bg: "var(--wg-surface)",
      fg: "var(--wg-ink)",
      border: "var(--wg-line)",
    },
  };
  const s = styles[tone ?? "default"];
  return (
    <span
      style={{
        padding: "3px 9px",
        background: s.bg,
        color: s.fg,
        border: `1px solid ${s.border}`,
        borderRadius: 12,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
      }}
    >
      {label}
    </span>
  );
}
