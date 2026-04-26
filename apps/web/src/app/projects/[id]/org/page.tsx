// /projects/[id]/org — Batch B IA reshape: NEW page.
//
// Per home_redesign HTML: the Organization page is "not a directory but
// a diagnostic" — shows where decision authority concentrates, where
// single-point risks live, and which members are over- vs under-loaded.
// Different intent from /status (project health) and /skills (capability
// graph) — this page is about authority distribution.
//
// v0 surfaces three things from data we already have:
//   1. Gate-keeper distribution (which class → which user) + a
//      single-point-risk badge per class
//   2. Member load — pending decisions/conflicts/suggestions per person
//   3. Member roles + skill tags (cross-link, not duplicated edit)
//
// Server component: one /state fetch + one /gate-keeper-map fetch.

import { getTranslations } from "next-intl/server";

import { Heading, Text } from "@/components/ui";
import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

type GateKeeperMap = {
  ok: boolean;
  map: Record<string, string>; // decision_class → user_id
  valid_classes: string[];
};

export default async function OrgPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("org");
  await requireUser(`/projects/${id}/org`);

  let state: ProjectState | null = null;
  let gateMap: GateKeeperMap | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }
  try {
    gateMap = await serverFetch<GateKeeperMap>(
      `/api/projects/${id}/gate-keeper-map`,
    );
  } catch {
    gateMap = null;
  }

  const members = state?.members ?? [];
  const memberById = new Map(members.map((m) => [m.user_id, m]));
  const validClasses = gateMap?.valid_classes ?? [];
  const map = gateMap?.map ?? {};

  // Single-point risk: a class is at risk if only one (or zero)
  // members are mapped to it, AND a target IS set. Empty mapping is
  // a separate state ("no gate-keeper") — also surfaced.
  const reverseMap: Record<string, string[]> = {};
  for (const [cls, uid] of Object.entries(map)) {
    if (!uid) continue;
    if (!reverseMap[uid]) reverseMap[uid] = [];
    reverseMap[uid].push(cls);
  }

  // Member load v0: pending suggestions targeting them + decisions
  // they resolved recently. We don't have a single "load" metric;
  // these proxies are honest for what data exists today.
  const decisionsPerResolver: Record<string, number> = {};
  for (const d of state?.decisions ?? []) {
    if (d.resolver_id) {
      decisionsPerResolver[d.resolver_id] =
        (decisionsPerResolver[d.resolver_id] ?? 0) + 1;
    }
  }

  return (
    <main style={{ padding: "20px 24px", maxWidth: 1100 }}>
      <header style={{ marginBottom: 28 }}>
        <Text variant="caption" muted style={{ letterSpacing: "0.14em" }}>
          {t("kicker")}
        </Text>
        <Heading level={1} style={{ marginTop: 8 }}>
          {t("title")}
        </Heading>
        <Text variant="body" muted style={{ marginTop: 6, maxWidth: 720 }}>
          {t("subtitle")}
        </Text>
      </header>

      {/* Gate-keeper distribution */}
      <section
        style={{
          marginBottom: 28,
          padding: 18,
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius-lg, 12px)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            marginBottom: 12,
          }}
        >
          <Heading level={2} style={{ fontSize: 16 }}>
            {t("gateKeepers.heading")}
          </Heading>
          <Text variant="caption" muted>
            {t("gateKeepers.subhead")}
          </Text>
        </div>
        {validClasses.length === 0 ? (
          <Text variant="body" muted>
            {t("gateKeepers.empty")}
          </Text>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {validClasses.map((cls) => {
              const uid = map[cls];
              const member = uid ? memberById.get(uid) : undefined;
              const hasGate = Boolean(uid);
              const isSinglePoint = hasGate && (reverseMap[uid!]?.length ?? 0) > 0;
              return (
                <div
                  key={cls}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 14px",
                    background: "var(--wg-surface)",
                    border: "1px solid var(--wg-line)",
                    borderRadius: "var(--wg-radius-sm, 4px)",
                  }}
                >
                  <Text
                    variant="mono"
                    style={{
                      fontWeight: 600,
                      width: 100,
                      color: "var(--wg-ink)",
                    }}
                  >
                    {cls}
                  </Text>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {hasGate ? (
                      <Text variant="body">
                        {member?.display_name ?? member?.username ?? uid}
                      </Text>
                    ) : (
                      <Text variant="body" muted>
                        {t("gateKeepers.unset")}
                      </Text>
                    )}
                  </div>
                  {!hasGate ? (
                    <span
                      style={{
                        padding: "2px 10px",
                        borderRadius: 999,
                        fontSize: 11,
                        fontFamily: "var(--wg-font-mono)",
                        fontWeight: 600,
                        background: "var(--wg-amber-soft)",
                        color: "var(--wg-amber)",
                      }}
                    >
                      {t("gateKeepers.noGate")}
                    </span>
                  ) : isSinglePoint ? (
                    <span
                      style={{
                        padding: "2px 10px",
                        borderRadius: 999,
                        fontSize: 11,
                        fontFamily: "var(--wg-font-mono)",
                        fontWeight: 600,
                        background: "rgba(220, 38, 38, 0.10)",
                        color: "var(--wg-danger)",
                      }}
                    >
                      {t("gateKeepers.singlePoint")}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Member load */}
      <section
        style={{
          padding: 18,
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius-lg, 12px)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            marginBottom: 12,
          }}
        >
          <Heading level={2} style={{ fontSize: 16 }}>
            {t("load.heading")}
          </Heading>
          <Text variant="caption" muted>
            {t("load.subhead")}
          </Text>
        </div>
        {members.length === 0 ? (
          <Text variant="body" muted>
            {t("load.empty")}
          </Text>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 10,
            }}
          >
            {members.map((m) => {
              const decisionCount = decisionsPerResolver[m.user_id] ?? 0;
              const gateClasses = reverseMap[m.user_id] ?? [];
              return (
                <div
                  key={m.user_id}
                  style={{
                    padding: 12,
                    background: "var(--wg-surface)",
                    border: "1px solid var(--wg-line)",
                    borderRadius: "var(--wg-radius-sm, 4px)",
                  }}
                >
                  <Text
                    variant="body"
                    style={{ fontWeight: 600, color: "var(--wg-ink)" }}
                  >
                    {m.display_name ?? m.username}
                  </Text>
                  <Text variant="caption" muted style={{ marginTop: 2 }}>
                    {m.role}
                    {m.license_tier && m.license_tier !== "full"
                      ? ` · ${m.license_tier}`
                      : ""}
                  </Text>
                  <div
                    style={{
                      marginTop: 8,
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 6,
                    }}
                  >
                    <span
                      style={{
                        padding: "1px 8px",
                        borderRadius: 10,
                        background: "var(--wg-surface-sunk)",
                        fontSize: 11,
                        fontFamily: "var(--wg-font-mono)",
                        color: "var(--wg-ink-soft)",
                      }}
                    >
                      {t("load.decisions", { count: decisionCount })}
                    </span>
                    {gateClasses.length > 0 ? (
                      <span
                        style={{
                          padding: "1px 8px",
                          borderRadius: 10,
                          background: "var(--wg-accent-soft)",
                          fontSize: 11,
                          fontFamily: "var(--wg-font-mono)",
                          color: "var(--wg-accent)",
                          fontWeight: 600,
                        }}
                      >
                        {t("load.gateClasses", { count: gateClasses.length })}
                      </span>
                    ) : null}
                  </div>
                  {(m.skill_tags?.length ?? 0) > 0 ? (
                    <div
                      style={{
                        marginTop: 6,
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 4,
                      }}
                    >
                      {m.skill_tags!.map((tag) => (
                        <span
                          key={tag}
                          style={{
                            padding: "1px 6px",
                            borderRadius: 10,
                            background: "var(--wg-surface-sunk)",
                            fontSize: 10,
                            fontFamily: "var(--wg-font-mono)",
                            color: "var(--wg-ink-soft)",
                          }}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}
