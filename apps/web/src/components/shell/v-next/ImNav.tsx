"use client";

// v-next ImNav — primary navigation per docs/shell-v-next.txt §2.
//
// Three sections:
//   1. 我的 Agent — agentPrimary (通用) + per-project navItem rows
//   2. 群组       — flat list of kind IN ('project','room')
//   3. 私聊       — kind='dm'
//
// Recency sort within each section happens server-side in AppShell.
// Section collapsibility matches prototype's NavSection (App.tsx:176-187).
//
// Wave 1 ports: + 创建群组 in the 群组 header opens NewRoomModal scoped
// to the active project; + 发起单聊 in the 私聊 header expands the
// existing NewDMPicker dropdown. Both reuse the legacy components
// verbatim — we're changing UX, not features.

import Link from "next/link";
import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";

import { fetchProjectMembers } from "@/lib/api";
import {
  NewRoomModal,
  type ProjectMemberLite,
} from "@/components/rooms/NewRoomModal";
import { NewDMPicker } from "../NewDMPicker";
import type { ShellProject } from "../AppShellClient";

import type {
  ShellPersonalAgent,
  ShellGroupItem,
  ShellDMItem,
  ShellWorkspace,
} from "./types";

import styles from "./ImNav.module.css";

interface Props {
  generalAgent: ShellPersonalAgent | null;
  projectAgents: ShellPersonalAgent[];
  groups: ShellGroupItem[];
  dms: ShellDMItem[];
  // Phase T workspaces tier — empty array hides the section. Same data
  // legacy AppSidebar already received.
  workspaces?: ShellWorkspace[];
  activeStreamId: string | null;
  // Project to scope NewRoomModal to. Comes from the focused stream;
  // null when on the global agent / a DM / no stream — in which case
  // the "+ 创建群组" affordance falls back to the user's first project,
  // or disables itself if the user has no projects.
  activeProjectId: string | null;
  currentUserId: string;
  onSelectStream: (streamId: string) => void;
}

export function ImNav({
  generalAgent,
  projectAgents,
  groups,
  dms,
  workspaces = [],
  activeStreamId,
  activeProjectId,
  currentUserId,
  onSelectStream,
}: Props) {
  const t = useTranslations("shellVNext");
  const [workspacesOpen, setWorkspacesOpen] = useState(true);
  const [projectAgentsOpen, setProjectAgentsOpen] = useState(true);
  const [groupsOpen, setGroupsOpen] = useState(true);
  const [dmsOpen, setDmsOpen] = useState(true);

  const generalLabel = t("generalAgent");
  const generalSub = t("generalAgentSubtitle");

  // NewRoomModal state. Scoped to the active project (or first
  // project agent as a fallback) so the affordance stays one-click.
  const fallbackProjectId =
    activeProjectId ?? projectAgents[0]?.project_id ?? null;
  const [roomModalOpen, setRoomModalOpen] = useState(false);
  const [roomMembers, setRoomMembers] = useState<ProjectMemberLite[] | null>(
    null,
  );
  const [roomMembersLoading, setRoomMembersLoading] = useState(false);
  const [roomScopeProjectId, setRoomScopeProjectId] = useState<string | null>(
    null,
  );

  const openRoomModal = useCallback(async () => {
    if (!fallbackProjectId) return;
    setRoomScopeProjectId(fallbackProjectId);
    setRoomMembersLoading(true);
    setRoomMembers(null);
    setRoomModalOpen(true);
    try {
      const list = await fetchProjectMembers(fallbackProjectId);
      // ProjectMemberLite expects {user_id, username, display_name}.
      setRoomMembers(
        list.map((m) => ({
          user_id: m.user_id,
          username: m.username ?? "",
          display_name: m.display_name ?? m.username ?? "",
        })),
      );
    } catch {
      // Modal stays open with an empty member list; NewRoomModal already
      // handles the "no members fetched" path with its own error UI.
      setRoomMembers([]);
    } finally {
      setRoomMembersLoading(false);
    }
  }, [fallbackProjectId]);

  // NewDMPicker takes a ShellProject[] but only reads `id` from each
  // entry. Build a minimal-shape projection from projectAgents so we
  // don't need to refetch /api/projects.
  const dmPickerProjects: ShellProject[] = projectAgents
    .filter((p): p is ShellPersonalAgent & { project_id: string } =>
      p.project_id !== null,
    )
    .map((p) => ({
      id: p.project_id,
      title: p.anchor_name,
      unread_count: p.unread_count,
      last_activity_at: p.last_activity_at,
    }));

  return (
    <aside
      className={styles.im}
      aria-label="Stream navigation"
      data-testid="vnext-imnav"
    >
      <div className={styles.imTop}>
        <strong>{t("personalAgentSection")}</strong>
        <div className={styles.imTopActions}>
          <button
            type="button"
            className={styles.miniBtn}
            aria-label="settings"
          >
            ⚙
          </button>
          <button type="button" className={styles.miniBtn} aria-label="new">
            ＋
          </button>
        </div>
      </div>

      {/* Workspaces — Phase T tier above projects. Hidden when the user
          belongs to none, so users without a workspace see the existing
          layout unchanged. Each row → /workspaces/{slug}. */}
      {workspaces.length > 0 && (
        <Section
          title={t("workspaces")}
          open={workspacesOpen}
          onToggle={() => setWorkspacesOpen((v) => !v)}
        >
          {workspaces.map((w) => (
            <Link
              key={w.id}
              href={`/workspaces/${w.slug}`}
              className={styles.navItem}
              data-testid={`vnext-imnav-workspace-${w.slug}`}
              title={w.name}
            >
              <span className={styles.face} aria-hidden>
                ⊞
              </span>
              <span className={styles.navText}>
                <span className={styles.label}>{w.name}</span>
              </span>
            </Link>
          ))}
        </Section>
      )}

      {/* agentPrimary — 通用 Agent (always visible if it exists) */}
      {generalAgent && (
        <button
          type="button"
          className={`${styles.agentPrimary} ${
            activeStreamId === generalAgent.stream_id ? styles.active : ""
          }`}
          onClick={() => onSelectStream(generalAgent.stream_id)}
          data-testid="vnext-imnav-general-agent"
        >
          <span className={styles.robot} aria-hidden />
          <span className={styles.navText}>
            <span className={styles.label}>{generalLabel}</span>
            <span className={styles.subLabel}>{generalSub}</span>
          </span>
          {generalAgent.unread_count > 0 && (
            <span className={`${styles.count} ${styles.countBlue}`}>
              {generalAgent.unread_count}
            </span>
          )}
        </button>
      )}

      {/* 项目 Agent — one row per project the user is in */}
      {projectAgents.length > 0 && (
        <Section
          title={t("projectAgents")}
          open={projectAgentsOpen}
          onToggle={() => setProjectAgentsOpen((v) => !v)}
        >
          {projectAgents.map((p) => (
            <NavItemBtn
              key={p.stream_id}
              face="P"
              label={t("projectAgentLabel", { project: p.anchor_name })}
              active={activeStreamId === p.stream_id}
              unread={p.unread_count}
              onClick={() => onSelectStream(p.stream_id)}
              testId={`vnext-imnav-project-agent-${p.project_id}`}
            />
          ))}
        </Section>
      )}

      {/* 群组 — flat list of kind in (project, room) */}
      <Section
        title={t("groups")}
        open={groupsOpen}
        onToggle={() => setGroupsOpen((v) => !v)}
        action={
          <button
            type="button"
            className={styles.miniBtn}
            onClick={(e) => {
              // Don't bubble — clicking + must not also collapse the
              // section (the surrounding sectionHead has its own toggle).
              e.stopPropagation();
              void openRoomModal();
            }}
            disabled={!fallbackProjectId}
            title={
              fallbackProjectId
                ? t("newGroupTip")
                : t("newGroupNoProjectTip")
            }
            aria-label={t("newGroup")}
            data-testid="vnext-imnav-new-group"
          >
            ＋
          </button>
        }
      >
        {groups.length === 0 ? (
          <p className={styles.emptyHint}>{t("noGroups")}</p>
        ) : (
          groups.map((g) => (
            <NavItemBtn
              key={g.stream_id}
              face="#"
              label={g.display_name ?? t("unnamedGroup")}
              active={activeStreamId === g.stream_id}
              unread={g.unread_count}
              onClick={() => onSelectStream(g.stream_id)}
              testId={`vnext-imnav-group-${g.stream_id}`}
            />
          ))
        )}
      </Section>

      {/* 私聊 */}
      <Section
        title={t("dms")}
        open={dmsOpen}
        onToggle={() => setDmsOpen((v) => !v)}
        // NewDMPicker is itself a small expandable list, so we render it
        // as the section's prefix content rather than a header button.
        prefix={
          dmPickerProjects.length > 0 ? (
            <div className={styles.dmPicker}>
              <NewDMPicker
                projects={dmPickerProjects}
                currentUserId={currentUserId}
              />
            </div>
          ) : null
        }
      >
        {dms.length === 0 ? (
          <p className={styles.emptyHint}>{t("noDMs")}</p>
        ) : (
          dms.map((d) => (
            <NavItemBtn
              key={d.stream_id}
              face={d.other_display_name.charAt(0).toUpperCase()}
              label={d.other_display_name}
              active={activeStreamId === d.stream_id}
              unread={d.unread_count}
              onClick={() => onSelectStream(d.stream_id)}
              testId={`vnext-imnav-dm-${d.other_user_id}`}
            />
          ))
        )}
      </Section>

      {roomScopeProjectId && (
        <NewRoomModal
          projectId={roomScopeProjectId}
          members={roomMembers ?? []}
          currentUserId={currentUserId}
          open={roomModalOpen && !roomMembersLoading}
          onClose={() => setRoomModalOpen(false)}
        />
      )}
    </aside>
  );
}

function Section({
  title,
  open,
  onToggle,
  action,
  prefix,
  children,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  // Small button rendered inline in the section header (e.g. "+ 创建群组").
  action?: React.ReactNode;
  // Content rendered above the items list when the section is open
  // (e.g. inline NewDMPicker).
  prefix?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className={`${styles.section} ${open ? styles.open : ""}`}>
      <div className={styles.sectionHead}>
        <span>{title}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {action}
          <button
            type="button"
            className={styles.miniBtn}
            onClick={onToggle}
            aria-label={open ? "collapse" : "expand"}
          >
            {open ? "⌃" : "⌄"}
          </button>
        </div>
      </div>
      {open && (
        <div className={styles.items}>
          {prefix}
          {children}
        </div>
      )}
    </div>
  );
}

function NavItemBtn({
  face,
  label,
  active,
  unread,
  onClick,
  testId,
}: {
  face: string;
  label: string;
  active: boolean;
  unread: number;
  onClick: () => void;
  testId?: string;
}) {
  return (
    <button
      type="button"
      className={`${styles.navItem} ${active ? styles.active : ""}`}
      onClick={onClick}
      data-testid={testId}
    >
      <span className={styles.face} aria-hidden>
        {face}
      </span>
      <span className={styles.navText}>
        <span className={styles.label}>{label}</span>
      </span>
      {unread > 0 && <span className={styles.count}>{unread}</span>}
    </button>
  );
}
