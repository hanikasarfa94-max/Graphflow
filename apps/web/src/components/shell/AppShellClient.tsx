"use client";

// AppShellClient — Phase Q interactive shell (client).
//
// Wraps the main pane with:
//   * <AppSidebar> on the left (navigation + projects + DMs + badge)
//   * <RoutedInboundDrawer> on the right (lazy-opened drawer with the
//     pending routed signals + full rich-options card)
//
// Drawer visibility + inbox count are co-owned state here — the sidebar
// badge and the drawer's "signal resolved" handler both need to update
// the count in lockstep. We expose an `openInbox()` handler through
// context so any card deep in the tree (e.g. the compact notification
// line PersonalStream still renders for inbound) can pop the drawer
// open.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { User } from "@/lib/api";

import { AppSidebar } from "./AppSidebar";
import { RoutedInboundDrawer } from "./RoutedInboundDrawer";
import { Topbar } from "./Topbar";

export interface ShellProject {
  id: string;
  title: string;
  unread_count: number;
  last_activity_at: string | null;
}

export interface ShellDM {
  stream_id: string;
  other_user_id: string;
  other_display_name: string;
  other_username: string;
  last_activity_at: string | null;
  unread_count: number;
}

// Phase T — workspace tier above project. Empty array = user belongs
// to no workspaces; sidebar hides the section entirely.
export interface ShellWorkspace {
  id: string;
  name: string;
  slug: string;
  role: string;
}

// Exported so the v-next AppShellClient can mount the same Provider
// without duplicating the React Context object — Topbar + RoutedInboundCard
// + every other consumer of useAppShell work in both shells unchanged.
export type ShellCtx = {
  inboxCount: number;
  setInboxCount: (n: number | ((prev: number) => number)) => void;
  openInbox: () => void;
  closeInbox: () => void;
  // Project list mounted in the sidebar — also exposed here so the
  // Topbar can resolve a UUID-shaped breadcrumb segment to a real
  // project title. Without this the breadcrumb collapses to "·" on
  // every project page.
  projects: ShellProject[];
};

export const ShellContext = createContext<ShellCtx | null>(null);

export function useAppShell(): ShellCtx {
  const v = useContext(ShellContext);
  if (!v) {
    // Components outside AppShell (e.g. /login surfaces) still import
    // this. Return a no-op so render doesn't crash.
    return {
      inboxCount: 0,
      setInboxCount: () => {},
      openInbox: () => {},
      closeInbox: () => {},
      projects: [],
    };
  }
  return v;
}

export function AppShellClient({
  user,
  projects,
  dms,
  initialInboxCount,
  workspaces,
  children,
}: {
  user: User;
  projects: ShellProject[];
  dms: ShellDM[];
  initialInboxCount: number;
  workspaces?: ShellWorkspace[];
  children: ReactNode;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [inboxCount, setInboxCount] = useState(initialInboxCount);

  const openInbox = useCallback(() => setDrawerOpen(true), []);
  const closeInbox = useCallback(() => setDrawerOpen(false), []);

  const ctx = useMemo<ShellCtx>(
    () => ({ inboxCount, setInboxCount, openInbox, closeInbox, projects }),
    [inboxCount, openInbox, closeInbox, projects],
  );

  return (
    <ShellContext.Provider value={ctx}>
      <div
        style={{
          display: "flex",
          minHeight: "100vh",
          background: "var(--wg-surface)",
        }}
      >
        <AppSidebar
          user={user}
          projects={projects}
          dms={dms}
          inboxCount={inboxCount}
          onOpenInbox={openInbox}
          workspaces={workspaces ?? []}
        />
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <Topbar />
          <main
            style={{
              flex: 1,
              minWidth: 0,
              overflowX: "auto",
            }}
          >
            {children}
          </main>
        </div>
        <RoutedInboundDrawer
          open={drawerOpen}
          onClose={closeInbox}
          onCountChange={setInboxCount}
        />
      </div>
    </ShellContext.Provider>
  );
}
