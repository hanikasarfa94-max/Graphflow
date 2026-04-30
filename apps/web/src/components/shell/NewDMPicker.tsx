"use client";

// NewDMPicker — Phase Q polish.
//
// Sidebar-level "+ Message teammate" affordance. Lazily fetches members
// across the user's projects, deduplicates by user_id, filters out self,
// and on pick calls POST /api/streams/dm then navigates to the stream.
//
// Kept minimal: not a modal, not a popup — a small expandable chip list
// in place, so the sidebar stays single-pane and predictable.

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";

import { createDMStream } from "@/lib/api";
import type { ShellProject } from "./AppShellClient";

type Member = {
  user_id: string;
  username: string;
  display_name: string;
};

// Endpoint returns a plain list (verified via curl 2026-04-19).
type MembersResponse = Member[];

export function NewDMPicker({
  projects,
  currentUserId,
}: {
  projects: ShellProject[];
  currentUserId: string;
}) {
  const router = useRouter();
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadMembers = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const all: Member[] = [];
      const seen = new Set<string>();
      for (const p of projects) {
        try {
          const r = await fetch(
            `/api/projects/${p.id}/members`,
            { credentials: "include" },
          );
          if (!r.ok) continue;
          const data = (await r.json()) as MembersResponse;
          for (const m of data ?? []) {
            if (m.user_id === currentUserId) continue;
            if (seen.has(m.user_id)) continue;
            seen.add(m.user_id);
            all.push(m);
          }
        } catch {
          // skip failed project
        }
      }
      all.sort((a, b) =>
        (a.display_name || a.username).localeCompare(b.display_name || b.username),
      );
      setMembers(all);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, [projects, currentUserId, loading]);

  const toggle = useCallback(() => {
    setOpen((v) => {
      const next = !v;
      if (next && members.length === 0) void loadMembers();
      return next;
    });
  }, [members.length, loadMembers]);

  const pick = useCallback(
    async (userId: string) => {
      if (busyId) return;
      setBusyId(userId);
      try {
        const res = await createDMStream(userId);
        router.push(`/streams/${res.stream.id}`);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "create failed");
      } finally {
        setBusyId(null);
      }
    },
    [busyId, router],
  );

  return (
    <div style={{ padding: "2px 12px 4px" }}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        data-testid="sidebar-new-dm"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "4px 0",
          background: "transparent",
          border: "none",
          color: "var(--wg-accent)",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          cursor: "pointer",
          width: "100%",
          textAlign: "left",
        }}
      >
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        <span>{t("shell.newDm")}</span>
      </button>
      {open ? (
        <div style={{ marginTop: 4 }}>
          {loading ? (
            <div
              style={{
                fontSize: 11,
                color: "var(--wg-ink-soft)",
                padding: "4px 4px 4px 14px",
              }}
            >
              {t("shell.loading")}
            </div>
          ) : error ? (
            <div
              style={{
                fontSize: 11,
                color: "var(--wg-accent)",
                padding: "4px 4px 4px 14px",
              }}
            >
              {error}
            </div>
          ) : members.length === 0 ? (
            <div
              style={{
                fontSize: 11,
                color: "var(--wg-ink-soft)",
                padding: "4px 4px 4px 14px",
              }}
            >
              {t("shell.noTeammates")}
            </div>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {members.map((m) => (
                <li key={m.user_id}>
                  <button
                    type="button"
                    onClick={() => void pick(m.user_id)}
                    disabled={busyId === m.user_id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      width: "100%",
                      padding: "4px 4px 4px 14px",
                      background: "transparent",
                      border: "none",
                      color: "var(--wg-ink)",
                      fontSize: 12,
                      cursor:
                        busyId === m.user_id ? "wait" : "pointer",
                      textAlign: "left",
                      opacity: busyId === m.user_id ? 0.5 : 1,
                    }}
                  >
                    <span aria-hidden>☁</span>
                    <span
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        flex: 1,
                      }}
                    >
                      {m.display_name || m.username}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
