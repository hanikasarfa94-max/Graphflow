import type { CSSProperties } from "react";
import { getTranslations } from "next-intl/server";

import { Card, EmptyState, Heading, Text } from "@/components/ui";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Org Composition diagnostic — HR/COO wedge view (v0, read-only).
//
// Answers "what's the health of this group's authority structure?" at a
// glance. Three sections:
//   A. Authority by class — each gated decision_class with its
//      gate-keeper + voter pool + health dot (SPOF / thin / healthy).
//   B. Member load — each member with authority counts, 30d observed
//      engagement, and a horizontal bar for load_score.
//   C. Shared-authority overlaps — pairs of members who co-hold
//      authority; the first pass at the "shared authority" network.
//
// No mutations. v1 adds drag-rebalance + simulate-departure behind
// owner-only permission gates.

type Health = "spof" | "thin" | "healthy";

type CompositionClass = {
  decision_class: string;
  gate_keeper_user_id: string | null;
  voter_pool: string[];
  pool_size: number;
  health: Health;
};

type CompositionMember = {
  user_id: string;
  display_name: string;
  role: "owner" | "member" | string;
  gate_count: number;
  vote_pool_count: number;
  gated_classes: string[];
  active_in_flight_count: number;
  votes_cast_30d: number;
  dissent_events_30d: number;
  decisions_resolved_30d: number;
  load_score: number;
};

type CompositionOverlap = {
  user_a_id: string;
  user_b_id: string;
  shared_classes: string[];
};

type CompositionSummary = {
  total_members: number;
  total_owners: number;
  classes_covered: number;
  spof_count: number;
  most_loaded_user_id: string | null;
  most_loaded_score: number;
};

type CompositionPayload = {
  ok: true;
  composition: {
    members: CompositionMember[];
    classes: CompositionClass[];
    overlaps: CompositionOverlap[];
    summary: CompositionSummary;
  };
};

function healthColor(h: Health): string {
  if (h === "spof") return "var(--wg-accent)";
  if (h === "thin") return "var(--wg-amber)";
  return "var(--wg-ok)";
}

function HealthDot({ health, label }: { health: Health; label: string }) {
  return (
    <span
      aria-label={label}
      title={label}
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: healthColor(health),
        flexShrink: 0,
      }}
    />
  );
}

const chipBase: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: "3px 8px",
  borderRadius: 999,
  fontSize: 12,
  fontFamily: "var(--wg-font-sans)",
  background: "var(--wg-surface-sunk)",
  color: "var(--wg-ink)",
  border: "1px solid var(--wg-line)",
  lineHeight: 1.2,
  whiteSpace: "nowrap",
};

const gateChip: CSSProperties = {
  ...chipBase,
  fontWeight: 600,
  background: "var(--wg-accent-soft, #fdf4ec)",
  color: "var(--wg-accent)",
  border: "1px solid var(--wg-accent)",
  padding: "4px 10px",
  fontSize: 13,
};

const pillBase: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "2px 7px",
  borderRadius: "var(--wg-radius-sm, 4px)",
  background: "var(--wg-surface-sunk)",
  color: "var(--wg-ink-soft)",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  lineHeight: 1.4,
  whiteSpace: "nowrap",
};

const rolePillOwner: CSSProperties = {
  ...pillBase,
  background: "var(--wg-accent-soft, #fdf4ec)",
  color: "var(--wg-accent)",
};

export default async function ProjectCompositionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations();
  await requireUser(`/projects/${id}/composition`);

  let payload: CompositionPayload | null = null;
  let errorMessage: string | null = null;
  try {
    payload = await serverFetch<CompositionPayload>(
      `/api/projects/${id}/composition`,
    );
  } catch (e) {
    errorMessage = e instanceof Error ? e.message : "failed to load composition";
  }

  const comp = payload?.composition ?? null;
  const classLabel = (cls: string): string => {
    const key = `composition.class_label_${cls}` as const;
    try {
      return t(key);
    } catch {
      return cls;
    }
  };
  const healthLabel = (h: Health): string => t(`composition.health_${h}`);
  const nameById = new Map(
    (comp?.members ?? []).map((m) => [m.user_id, m.display_name]),
  );
  const memberMap = new Map((comp?.members ?? []).map((m) => [m.user_id, m]));
  const maxLoad =
    comp && comp.members.length > 0
      ? Math.max(...comp.members.map((m) => m.load_score), 1)
      : 1;

  return (
    <main>
      <header style={{ marginBottom: 20 }}>
        <Text
          variant="caption"
          muted
          style={{
            fontFamily: "var(--wg-font-mono)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          {t("composition.eyebrow")}
        </Text>
        <Heading level={2} style={{ marginTop: 4 }}>
          {t("composition.title")}
        </Heading>
        {comp ? (
          <Text variant="body" muted style={{ marginTop: 6 }}>
            {t("composition.summary", {
              members: comp.summary.total_members,
              covered: comp.summary.classes_covered,
              spof: comp.summary.spof_count,
            })}
          </Text>
        ) : null}
      </header>

      {errorMessage ? (
        <Card>
          <Text
            variant="body"
            style={{
              color: "var(--wg-accent)",
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            {t("composition.loadError")} — {errorMessage}
          </Text>
        </Card>
      ) : null}

      {comp ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* ---- Section A: Authority by class ---- */}
          <Card title={t("composition.sectionA_title")}>
            <Text variant="caption" muted style={{ marginBottom: 12 }}>
              {t("composition.sectionA_subtitle")}
            </Text>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 12,
                marginTop: 12,
              }}
            >
              {comp.classes.map((cls) => {
                const gateName = cls.gate_keeper_user_id
                  ? nameById.get(cls.gate_keeper_user_id) ??
                    cls.gate_keeper_user_id
                  : null;
                return (
                  <div
                    key={cls.decision_class}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      paddingBottom: 10,
                      borderBottom: "1px solid var(--wg-line-soft)",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        flexWrap: "wrap",
                      }}
                    >
                      <HealthDot
                        health={cls.health}
                        label={healthLabel(cls.health)}
                      />
                      <Text
                        variant="body"
                        style={{
                          fontWeight: 600,
                          minWidth: 120,
                        }}
                      >
                        {classLabel(cls.decision_class)}
                      </Text>
                      <Text
                        variant="caption"
                        muted
                        style={{ fontFamily: "var(--wg-font-mono)" }}
                      >
                        {t("composition.poolSize", { n: cls.pool_size })}
                      </Text>
                      <Text
                        variant="caption"
                        muted
                        style={{ marginLeft: "auto" }}
                      >
                        {healthLabel(cls.health)}
                      </Text>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        flexWrap: "wrap",
                        paddingLeft: 20,
                      }}
                    >
                      {gateName ? (
                        <span style={gateChip}>
                          <span aria-hidden>⚖</span>
                          {t("composition.gateKeeper")}: {gateName}
                        </span>
                      ) : (
                        <span
                          style={{
                            ...chipBase,
                            color: "var(--wg-ink-faint)",
                            fontStyle: "italic",
                          }}
                        >
                          {t("composition.gateKeeperNone")}
                        </span>
                      )}
                      <Text
                        variant="caption"
                        muted
                        style={{ marginLeft: 4 }}
                      >
                        {t("composition.voterPool")}:
                      </Text>
                      {cls.voter_pool.map((uid) => {
                        const name = nameById.get(uid) ?? uid;
                        const isGate = uid === cls.gate_keeper_user_id;
                        return (
                          <span
                            key={uid}
                            style={{
                              ...chipBase,
                              ...(isGate
                                ? {
                                    color: "var(--wg-accent)",
                                    borderColor: "var(--wg-accent)",
                                  }
                                : null),
                            }}
                          >
                            {name}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          {/* ---- Section B: Member load ---- */}
          <Card title={t("composition.sectionB_title")}>
            <Text variant="caption" muted style={{ marginBottom: 12 }}>
              {t("composition.sectionB_subtitle")}
            </Text>
            {comp.members.length === 0 ? (
              <EmptyState>{t("composition.noMembers")}</EmptyState>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  padding: 0,
                  margin: "12px 0 0",
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                {comp.members.map((m) => {
                  const pct = Math.round((m.load_score / maxLoad) * 100);
                  return (
                    <li
                      key={m.user_id}
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 6,
                        paddingBottom: 10,
                        borderBottom: "1px solid var(--wg-line-soft)",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          flexWrap: "wrap",
                        }}
                      >
                        <Text variant="body" style={{ fontWeight: 600 }}>
                          {m.display_name}
                        </Text>
                        <span
                          style={
                            m.role === "owner" ? rolePillOwner : pillBase
                          }
                        >
                          {m.role === "owner"
                            ? t("composition.roleOwner")
                            : t("composition.roleMember")}
                        </span>
                        {m.gate_count > 0 ? (
                          <span style={pillBase}>
                            {t("composition.gates_pill", { n: m.gate_count })}
                          </span>
                        ) : null}
                        <span style={pillBase}>
                          {t("composition.pools_pill", {
                            n: m.vote_pool_count,
                          })}
                        </span>
                        {m.active_in_flight_count > 0 ? (
                          <span
                            style={{
                              ...pillBase,
                              color: "var(--wg-amber)",
                            }}
                          >
                            {t("composition.inflight_pill", {
                              n: m.active_in_flight_count,
                            })}
                          </span>
                        ) : null}
                        <Text
                          variant="caption"
                          muted
                          style={{
                            marginLeft: "auto",
                            fontFamily: "var(--wg-font-mono)",
                          }}
                        >
                          {t("composition.loadScore", { n: m.load_score })}
                        </Text>
                      </div>
                      <div
                        role="progressbar"
                        aria-valuenow={m.load_score}
                        aria-valuemin={0}
                        aria-valuemax={maxLoad}
                        aria-label={t("composition.loadAria", {
                          n: m.load_score,
                        })}
                        style={{
                          height: 6,
                          background: "var(--wg-surface-sunk)",
                          borderRadius: 3,
                          overflow: "hidden",
                        }}
                      >
                        <div
                          style={{
                            width: `${pct}%`,
                            height: "100%",
                            background:
                              m.load_score === 0
                                ? "var(--wg-line)"
                                : "var(--wg-accent)",
                            transition: "width 160ms ease-out",
                          }}
                        />
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: 14,
                          flexWrap: "wrap",
                          fontSize: 11,
                          fontFamily: "var(--wg-font-mono)",
                          color: "var(--wg-ink-soft)",
                        }}
                      >
                        <span>
                          {t("composition.votes30d", { n: m.votes_cast_30d })}
                        </span>
                        <span>
                          {t("composition.decisions30d", {
                            n: m.decisions_resolved_30d,
                          })}
                        </span>
                        <span>
                          {t("composition.dissent30d", {
                            n: m.dissent_events_30d,
                          })}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          {/* ---- Section C: Shared authority ---- */}
          <Card title={t("composition.sectionC_title")}>
            <Text variant="caption" muted style={{ marginBottom: 12 }}>
              {t("composition.sectionC_subtitle")}
            </Text>
            {comp.overlaps.length === 0 ? (
              <EmptyState>{t("composition.sectionC_empty")}</EmptyState>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  padding: 0,
                  margin: "12px 0 0",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                {comp.overlaps.map((o) => {
                  const a = memberMap.get(o.user_a_id);
                  const b = memberMap.get(o.user_b_id);
                  const aName = a?.display_name ?? o.user_a_id;
                  const bName = b?.display_name ?? o.user_b_id;
                  const classes = o.shared_classes
                    .map((c) => classLabel(c))
                    .join(", ");
                  return (
                    <li
                      key={`${o.user_a_id}:${o.user_b_id}`}
                      style={{
                        display: "flex",
                        alignItems: "baseline",
                        gap: 8,
                        fontSize: 13,
                        color: "var(--wg-ink)",
                      }}
                    >
                      <Text variant="body" style={{ fontWeight: 600 }}>
                        {aName}
                      </Text>
                      <span
                        aria-hidden
                        style={{ color: "var(--wg-ink-faint)" }}
                      >
                        ↔
                      </span>
                      <Text variant="body" style={{ fontWeight: 600 }}>
                        {bName}
                      </Text>
                      <Text variant="caption" muted>
                        {t("composition.sharedPair", { classes })}
                      </Text>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>
      ) : null}
    </main>
  );
}
