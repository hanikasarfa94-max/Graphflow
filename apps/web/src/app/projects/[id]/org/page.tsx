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

import { Heading, PageHeader, Tag, Text } from "@/components/ui";
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
      <PageHeader title={t("title")} subtitle={t("subtitle")} />

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
                    <Tag tone="amber">{t("gateKeepers.noGate")}</Tag>
                  ) : isSinglePoint ? (
                    <Tag tone="danger">{t("gateKeepers.singlePoint")}</Tag>
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
                    <Tag tone="neutral">
                      {t("load.decisions", { count: decisionCount })}
                    </Tag>
                    {gateClasses.length > 0 ? (
                      <Tag tone="accent">
                        {t("load.gateClasses", { count: gateClasses.length })}
                      </Tag>
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
