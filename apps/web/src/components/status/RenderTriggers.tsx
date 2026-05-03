"use client";

// /projects/[id]/status → bottom panel (Phase Q.7).
//
// Until this shipped, postmortem + handoff renders existed at
// /projects/[id]/renders/[slug] but nothing in the UI triggered them.
// This surface is the visible entry point: two sections ("Postmortem"
// and "Handoff docs"), each with a button that:
//   1) POSTs the regenerate endpoint (backend caches + generates if no
//      cached copy exists — same behavior as first-visit to the render
//      page, but with an explicit user gesture)
//   2) Navigates to the render view so the user sees the output.
//
// The postmortem side also does a GET first on mount so — if a cached
// copy exists — we can surface a "Last generated X ago · View | Regenerate"
// affordance instead of bare "Generate". Handoff buttons stay simple per
// spec (the handoff doc is per-member, and a full matrix of "last
// generated" badges would overwhelm the panel for teams of 5+).

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui";
import {
  getPostmortemRender,
  regenerateHandoffRender,
  regeneratePostmortemRender,
  type PostmortemRender,
  type ProjectState,
} from "@/lib/api";

import { Panel } from "./Panel";
import { formatIso } from "@/lib/time";

type Member = ProjectState["members"][number];

export function RenderTriggers({
  projectId,
  members,
  currentUserId,
}: {
  projectId: string;
  members: Member[];
  currentUserId: string;
}) {
  const t = useTranslations();
  const router = useRouter();

  // Postmortem cached-render probe — fires once on mount. 404 / "not
  // generated yet" is an expected state; we just don't show the "Last
  // generated" line in that case.
  const [existing, setExisting] = useState<PostmortemRender | null>(null);
  const [probeLoading, setProbeLoading] = useState(true);
  // Button-level busy flags — keyed by the action, so two separate
  // buttons don't share a single disabled state.
  const [postmortemBusy, setPostmortemBusy] = useState(false);
  const [handoffBusyUserId, setHandoffBusyUserId] = useState<string | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await getPostmortemRender(projectId);
        if (!cancelled) setExisting(r);
      } catch {
        // 404 / 500 / "no cached render" all fall here — treat as
        // "nothing generated yet" and let the normal Generate button
        // handle the request.
      } finally {
        if (!cancelled) setProbeLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function handleGeneratePostmortem() {
    setPostmortemBusy(true);
    setError(null);
    try {
      await regeneratePostmortemRender(projectId);
      router.push(`/projects/${projectId}/renders/postmortem`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed");
      setPostmortemBusy(false);
    }
  }

  function handleViewPostmortem() {
    router.push(`/projects/${projectId}/renders/postmortem`);
  }

  async function handleGenerateHandoff(userId: string) {
    setHandoffBusyUserId(userId);
    setError(null);
    try {
      await regenerateHandoffRender(projectId, userId);
      router.push(`/projects/${projectId}/renders/handoff:${userId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed");
      setHandoffBusyUserId(null);
    }
  }

  const otherMembers = members.filter((m) => m.user_id !== currentUserId);

  return (
    <Panel title={t("status.renderTriggers.title")}>
      {error ? (
        <div
          role="alert"
          style={{
            marginBottom: 12,
            padding: "8px 12px",
            border: "1px solid var(--wg-accent)",
            color: "var(--wg-accent)",
            fontSize: 13,
            borderRadius: "var(--wg-radius)",
          }}
        >
          {error}
        </div>
      ) : null}

      {/* Postmortem section */}
      <div
        style={{
          display: "grid",
          gap: 8,
          padding: "12px 14px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          background: "var(--wg-surface)",
          marginBottom: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--wg-ink)" }}>
            {t("status.renderTriggers.postmortem.heading")}
          </div>
          {probeLoading ? (
            <div
              style={{
                fontSize: 11,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
              }}
            >
              {t("states.loading")}
            </div>
          ) : existing ? (
            <div
              style={{
                fontSize: 11,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
              }}
            >
              {t("status.renderTriggers.postmortem.lastGenerated", {
                time: formatIso(existing.generated_at),
              })}
            </div>
          ) : null}
        </div>
        <div
          style={{
            fontSize: 13,
            color: "var(--wg-ink-soft)",
          }}
        >
          {t("status.renderTriggers.postmortem.description")}
        </div>
        <div
          style={{
            display: "flex",
            gap: 8,
            marginTop: 4,
            flexWrap: "wrap",
          }}
        >
          {existing ? (
            <>
              <Button
                variant="primary"
                onClick={handleViewPostmortem}
                disabled={postmortemBusy}
              >
                {t("status.renderTriggers.postmortem.view")}
              </Button>
              <Button
                variant="ghost"
                onClick={handleGeneratePostmortem}
                disabled={postmortemBusy}
              >
                {postmortemBusy
                  ? t("states.loading")
                  : t("status.renderTriggers.postmortem.regenerate")}
              </Button>
            </>
          ) : (
            <Button
              variant="primary"
              onClick={handleGeneratePostmortem}
              disabled={postmortemBusy}
            >
              {postmortemBusy
                ? t("states.loading")
                : t("status.renderTriggers.postmortem.generate")}
            </Button>
          )}
        </div>
      </div>

      {/* Handoff section */}
      <div
        style={{
          display: "grid",
          gap: 8,
          padding: "12px 14px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          background: "var(--wg-surface)",
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--wg-ink)" }}>
          {t("status.renderTriggers.handoff.heading")}
        </div>
        <div style={{ fontSize: 13, color: "var(--wg-ink-soft)" }}>
          {t("status.renderTriggers.handoff.description")}
        </div>
        {otherMembers.length === 0 ? (
          <div
            style={{
              padding: "12px",
              color: "var(--wg-ink-soft)",
              fontSize: 13,
              textAlign: "center",
              border: "1px dashed var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              marginTop: 4,
            }}
          >
            {t("status.renderTriggers.handoff.empty")}
          </div>
        ) : (
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: "4px 0 0",
              display: "grid",
              gap: 6,
            }}
          >
            {otherMembers.map((m) => (
              <HandoffRow
                key={m.user_id}
                member={m}
                busy={handoffBusyUserId === m.user_id}
                disabled={handoffBusyUserId !== null}
                label={t("status.renderTriggers.handoff.generate")}
                busyLabel={t("states.loading")}
                onGenerate={() => handleGenerateHandoff(m.user_id)}
              />
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}

function HandoffRow({
  member,
  busy,
  disabled,
  label,
  busyLabel,
  onGenerate,
}: {
  member: Member;
  busy: boolean;
  disabled: boolean;
  label: string;
  busyLabel: string;
  onGenerate: () => void;
}) {
  const initial =
    (member.display_name?.trim()?.[0] ??
      member.username?.trim()?.[0] ??
      "?"
    ).toUpperCase();
  return (
    <li
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 10px",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface-raised)",
        flexWrap: "wrap",
      }}
    >
      <div
        aria-hidden="true"
        style={{
          flexShrink: 0,
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: "var(--wg-ink)",
          color: "var(--wg-surface-raised)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 12,
          fontWeight: 600,
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {initial}
      </div>
      <div style={{ flex: 1, minWidth: 120 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "var(--wg-ink)",
          }}
        >
          {member.display_name}
        </div>
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          {member.role}
        </div>
      </div>
      <Button
        variant="ghost"
        onClick={onGenerate}
        disabled={disabled}
      >
        {busy ? busyLabel : label}
      </Button>
    </li>
  );
}


