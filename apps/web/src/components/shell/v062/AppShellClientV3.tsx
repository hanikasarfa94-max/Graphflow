"use client";

// AppShellClientV3 — interactive shell for the v0.6.2 IA.
//
// Composes:
//   * <AppSidebarV3> on the left (5-surface global nav, no project tree)
//   * <ScopeBand> below the topbar (project scope picker; persistent)
//   * <DrawerHostProvider> wrapping the main pane so any descendant can
//     open the right-side drawer via useDrawer().open({ type, props }).
//
// Replaces AppShellClient.tsx when layout.tsx is flipped in the Phase A
// big-bang commit. Until then, both shells coexist in the tree and only
// the legacy one is wired.
//
// Active scope is client-side state for Phase A.2 (localStorage
// persistence). Phase B adds /api/user/active-scope so the choice
// follows the user across devices.

import { useCallback, useEffect, useState, type ReactNode } from "react";

import type { User } from "@/lib/api";

import { AppSidebarV3 } from "./AppSidebarV3";
import { DrawerHostProvider } from "./DrawerHost";
import { ScopeBand, type Scope, type ScopeMode } from "./ScopeBand";

const SCOPE_STORAGE_KEY = "wg:v062:active-scope";

type StoredScope = { scopeId: string | null; mode: ScopeMode };

function loadStoredScope(): StoredScope {
  if (typeof window === "undefined") {
    return { scopeId: null, mode: "all_accessible" };
  }
  try {
    const raw = window.localStorage.getItem(SCOPE_STORAGE_KEY);
    if (!raw) return { scopeId: null, mode: "all_accessible" };
    const parsed = JSON.parse(raw) as Partial<StoredScope>;
    const mode: ScopeMode =
      parsed.mode === "current_focus" ||
      parsed.mode === "all_accessible" ||
      parsed.mode === "no_focus"
        ? parsed.mode
        : "all_accessible";
    return {
      scopeId: typeof parsed.scopeId === "string" ? parsed.scopeId : null,
      mode,
    };
  } catch {
    return { scopeId: null, mode: "all_accessible" };
  }
}

export function AppShellClientV3({
  user,
  scopes,
  children,
}: {
  user: User;
  scopes: Scope[];
  children: ReactNode;
}) {
  // Initialize default on the server (`all_accessible`), then hydrate
  // from localStorage on the client. Avoids SSR hydration mismatch.
  const [scopeState, setScopeState] = useState<StoredScope>({
    scopeId: null,
    mode: "all_accessible",
  });

  useEffect(() => {
    setScopeState(loadStoredScope());
  }, []);

  const onScopeChange = useCallback((next: StoredScope) => {
    setScopeState(next);
    try {
      window.localStorage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Private-mode / quota — non-fatal.
    }
  }, []);

  return (
    <DrawerHostProvider>
      <div
        style={{
          display: "flex",
          minHeight: "100vh",
          background: "var(--wg-paper)",
        }}
      >
        <AppSidebarV3 user={user} />
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          {/* Topbar slot — Phase A.2 keeps the existing Topbar wired so
              search + breadcrumb + new-menu keep working. Topbar v3
              with the create-menu allowlist + notification bell drawer
              lands in Phase A.4. */}
          <ScopeBand
            scopes={scopes}
            activeScopeId={scopeState.scopeId}
            mode={scopeState.mode}
            onChange={onScopeChange}
          />
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
      </div>
    </DrawerHostProvider>
  );
}
