import { getTranslations } from "next-intl/server";

import type { ProjectState } from "@/lib/api";

import { InlineMemberInvite } from "./InlineMemberInvite";
import { EmptyState, Panel } from "./Panel";

type Member = ProjectState["members"][number];

// Grid of member cards. For v1, everyone is rendered as "online" — presence
// is a v2 polish per Phase E's decision. License-tier observers get a badge.
// Owners get an inline invite affordance below the grid so adding teammates
// happens where the team list lives, not in /settings.
export async function MembersPanel({
  members,
  projectId,
  currentUserId,
}: {
  members: Member[];
  projectId?: string;
  currentUserId?: string;
}) {
  const t = await getTranslations();

  const isOwner = Boolean(
    currentUserId &&
      members.some(
        (m) => m.user_id === currentUserId && m.role === "owner",
      ),
  );
  const existingUsernames = members.map((m) => m.username).filter(Boolean);

  if (!members || members.length === 0) {
    return (
      <Panel title={t("status.members.title")}>
        <EmptyState>{t("status.members.empty")}</EmptyState>
        {isOwner && projectId ? (
          <InlineMemberInvite
            projectId={projectId}
            existingUsernames={existingUsernames}
          />
        ) : null}
      </Panel>
    );
  }

  return (
    <Panel
      title={t("status.members.title")}
      subtitle={String(members.length)}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
          gap: 12,
        }}
      >
        {members.map((m) => (
          <MemberCard
            key={m.user_id}
            member={m}
            observerLabel={t("status.members.observer")}
            roleLabel={t("status.members.roleLabel")}
            presenceLabel={t("stream.presence.online")}
            roleTranslations={{
              owner: t("status.members.role.owner"),
              member: t("status.members.role.member"),
              observer: t("status.members.role.observer"),
            }}
          />
        ))}
      </div>
      {isOwner && projectId ? (
        <InlineMemberInvite
          projectId={projectId}
          existingUsernames={existingUsernames}
        />
      ) : null}
    </Panel>
  );
}

function MemberCard({
  member,
  observerLabel,
  roleLabel,
  presenceLabel,
  roleTranslations,
}: {
  member: Member;
  observerLabel: string;
  roleLabel: string;
  presenceLabel: string;
  roleTranslations: Record<"owner" | "member" | "observer", string>;
}) {
  const roleKey = (member.role as "owner" | "member" | "observer") ?? "member";
  const localizedRole = roleTranslations[roleKey] ?? member.role;
  const initial =
    (member.display_name?.trim()?.[0] ??
      member.username?.trim()?.[0] ??
      "?"
    ).toUpperCase();
  const isObserver = member.license_tier === "observer";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 12px",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface)",
      }}
    >
      <div
        aria-hidden="true"
        title={presenceLabel}
        style={{
          position: "relative",
          flexShrink: 0,
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: "var(--wg-ink)",
          color: "var(--wg-surface-raised)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 14,
          fontWeight: 600,
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {initial}
        <span
          style={{
            position: "absolute",
            right: -2,
            bottom: -2,
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: "var(--wg-ok)",
            border: "2px solid var(--wg-surface-raised)",
          }}
        />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "var(--wg-ink)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={member.display_name}
        >
          {member.display_name}
        </div>
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginTop: 2,
          }}
        >
          <span>{roleLabel}: {localizedRole}</span>
          {isObserver ? (
            <span
              style={{
                padding: "1px 6px",
                borderRadius: 10,
                background: "var(--wg-accent)",
                color: "var(--wg-surface-raised)",
                fontSize: 10,
                fontWeight: 600,
              }}
            >
              {observerLabel}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
