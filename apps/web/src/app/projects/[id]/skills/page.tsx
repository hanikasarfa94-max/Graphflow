import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { serverFetch } from "@/lib/auth";
import type { SkillAtlasPayload } from "@/lib/api";

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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 18,
          marginTop: 22,
        }}
      >
        {payload.members.map((m) => (
          <MemberCard key={m.user_id} card={m} t={t} />
        ))}
      </div>
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
    <header style={{ marginBottom: 22 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: 28,
            fontWeight: 600,
            color: "var(--wg-ink)",
          }}
        >
          {title}
        </h1>
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
      </div>
      <p
        style={{
          margin: "8px 0 0",
          color: "var(--wg-ink-soft)",
          fontSize: 14,
          lineHeight: 1.55,
          maxWidth: 640,
        }}
      >
        {subtitle}
      </p>
    </header>
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
        borderRadius: 8,
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
}: {
  card: SkillAtlasPayload["members"][number];
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  return (
    <article
      style={{
        padding: 18,
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: 8,
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
        }}
      >
        <span>{t("card.messagesTag", { n: card.observed_tallies.messages_posted_30d ?? 0 })}</span>
        <span>{t("card.decisionsTag", { n: card.observed_tallies.decisions_resolved_30d ?? 0 })}</span>
        <span>{t("card.risksTag", { n: card.observed_tallies.risks_owned ?? 0 })}</span>
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

function SkillChip({
  label,
  tone,
}: {
  label: string;
  tone?: "observed" | "validated" | "gap";
}) {
  const styles: Record<string, { bg: string; fg: string; border: string }> = {
    observed: {
      bg: "rgba(77,122,74,0.1)",
      fg: "var(--wg-ok)",
      border: "var(--wg-ok)",
    },
    validated: {
      bg: "rgba(77,122,74,0.18)",
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
