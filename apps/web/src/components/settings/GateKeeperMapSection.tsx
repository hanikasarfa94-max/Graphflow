"use client";

// Phase R v1 — Scene 2 project settings. Owner-only. Maps
// `decision_class → user_id` so the edge agent can emit
// `route_kind='gated'` and the GatedProposalService knows who gets the
// sign-off card. Empty string in any class dropdown clears that class.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  DECISION_CLASSES,
  api,
  getGateKeeperMap,
  putGateKeeperMap,
  type DecisionClass,
} from "@/lib/api";

type MemberRow = {
  user_id: string;
  username: string;
  display_name: string;
  role: string;
};

type ProjectStateLite = {
  members: MemberRow[];
};

type Props = {
  projectId: string;
};

export function GateKeeperMapSection({ projectId }: Props) {
  const t = useTranslations("gateKeeperMap");
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [map, setMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [state, gate] = await Promise.all([
        api<ProjectStateLite>(`/api/projects/${projectId}/state`),
        getGateKeeperMap(projectId),
      ]);
      setMembers(state.members ?? []);
      setMap(gate.map ?? {});
    } catch (e) {
      const msg = e instanceof ApiError ? `error ${e.status}` : "load failed";
      setLoadError(msg);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const memberById = useMemo(() => {
    const m = new Map<string, MemberRow>();
    for (const row of members) m.set(row.user_id, row);
    return m;
  }, [members]);

  async function handleSave(next: Record<string, string>) {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await putGateKeeperMap(projectId, next);
      setMap(res.map);
      setSavedAt(Date.now());
    } catch (e) {
      if (e instanceof ApiError) {
        const body = e.body as
          | { message?: unknown; detail?: unknown }
          | undefined;
        const msg =
          (body && typeof body.message === "string" && body.message) ||
          (body && typeof body.detail === "string" && body.detail) ||
          `error ${e.status}`;
        setSaveError(String(msg));
      } else {
        setSaveError("save failed");
      }
    } finally {
      setSaving(false);
    }
  }

  function handleChange(cls: DecisionClass, userId: string) {
    const next = { ...map };
    if (!userId) delete next[cls];
    else next[cls] = userId;
    void handleSave(next);
  }

  return (
    <section
      data-testid="gate-keeper-map-section"
      style={{
        marginTop: 24,
        padding: 20,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      <h2 style={{ marginTop: 0 }}>{t("heading")}</h2>
      <p style={{ fontSize: 13, color: "var(--wg-ink-soft)" }}>
        {t("help")}
      </p>

      {loadError ? (
        <p
          role="alert"
          style={{ color: "var(--wg-accent)", fontSize: 13 }}
        >
          {loadError}
        </p>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1fr) minmax(220px, 1fr)",
          gap: 12,
          marginTop: 12,
        }}
      >
        {DECISION_CLASSES.map((cls) => {
          const currentUserId = map[cls] ?? "";
          const currentMember = memberById.get(currentUserId);
          return (
            <label
              key={cls}
              data-testid="gate-keeper-row"
              data-decision-class={cls}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                padding: 10,
                background: "var(--wg-surface)",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius-sm, 4px)",
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  fontFamily: "var(--wg-font-mono)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: "var(--wg-ink-faint)",
                }}
              >
                {t(`class.${cls}`)}
              </span>
              <select
                value={currentUserId}
                onChange={(e) => handleChange(cls, e.target.value)}
                disabled={saving || loading}
                data-testid="gate-keeper-select"
                data-decision-class={cls}
                style={{
                  padding: "6px 8px",
                  background: "var(--wg-surface-raised, var(--wg-surface))",
                  color: "var(--wg-ink)",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius-sm, 4px)",
                  fontSize: 13,
                }}
              >
                <option value="">{t("unassigned")}</option>
                {members.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.display_name || m.username}
                  </option>
                ))}
              </select>
              {currentMember ? (
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--wg-ink-soft)",
                    fontFamily: "var(--wg-font-mono)",
                  }}
                >
                  {t("currentlyMapped", { role: currentMember.role })}
                </span>
              ) : (
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--wg-ink-faint)",
                    fontStyle: "italic",
                  }}
                >
                  {t("noGateKeeper")}
                </span>
              )}
            </label>
          );
        })}
      </div>

      <div
        style={{
          marginTop: 12,
          display: "flex",
          gap: 12,
          alignItems: "center",
          minHeight: 20,
        }}
      >
        {saving ? (
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            {t("saving")}
          </span>
        ) : savedAt ? (
          <span
            data-testid="gate-keeper-saved"
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ok)",
            }}
          >
            {t("saved")}
          </span>
        ) : null}
        {saveError ? (
          <span
            role="alert"
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-accent)",
            }}
          >
            {saveError}
          </span>
        ) : null}
      </div>
    </section>
  );
}
