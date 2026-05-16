"use client";

// AppSidebarV3 — 5-surface global navigation for the v0.6.2 shell.
//
// Replaces the project-tree sidebar with the locked nav from
// graphflow_handoff_v062/FRONTEND_IMPLEMENTATION.md:
//
//   My AI         /my-ai
//   Conversations /conversations
//   Tasks         /tasks
//   Documents·KB  /docs
//   Flow Center   /flow-center
//
// Forbidden in primary nav (per INVARIANT_TESTS.md):
//   Project, Graph, Memory, Capability, "Embedded Views"
//
// Project lives in the ScopeBand below the topbar — scope, not page.

import {
  BookOpen,
  CheckSquare,
  MessageSquare,
  Sparkles,
  Workflow,
  LogOut,
  User as UserIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import type { User } from "@/lib/api";

// 5-surface nav locked. i18n keys at shellV062.nav.*.
// Adding a 6th item violates the INVARIANT_TESTS.md primary-nav check.
const NAV_ITEMS = [
  { key: "myAi", href: "/my-ai", icon: Sparkles },
  { key: "conversations", href: "/conversations", icon: MessageSquare },
  { key: "tasks", href: "/tasks", icon: CheckSquare },
  { key: "docs", href: "/docs", icon: BookOpen },
  { key: "flowCenter", href: "/flow-center", icon: Workflow },
] as const;

const SIDEBAR_WIDTH = 240;

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

const linkBase: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  // 12px vertical + 14px horizontal padding lands the row at 44px tall
  // (12 + 14px line-height body + 12 + 2 hairline = 44). Hits the WCAG
  // 44px touch-target minimum without growing the sidebar.
  padding: "12px 14px",
  minHeight: 44,
  fontSize: "var(--wg-fs-body)",
  fontFamily: "var(--wg-font-sans)",
  color: "var(--wg-ink-soft)",
  textDecoration: "none",
  borderRadius: "var(--wg-radius-sm)",
  fontWeight: 500,
  transition: "background var(--wg-dur-short) var(--wg-ease-move), color var(--wg-dur-short) var(--wg-ease-move)",
};

const linkActive: CSSProperties = {
  background: "var(--wg-accent-soft)",
  color: "var(--wg-accent)",
  fontWeight: 600,
};

export function AppSidebarV3({
  user,
}: {
  user: User;
}) {
  const pathname = usePathname();
  const t = useTranslations("shellV062");

  return (
    <aside
      aria-label="Primary navigation"
      data-testid="app-sidebar-v062"
      style={{
        width: SIDEBAR_WIDTH,
        minWidth: SIDEBAR_WIDTH,
        height: "100vh",
        position: "sticky",
        top: 0,
        background: "var(--wg-surface)",
        borderRight: "1px solid var(--wg-line)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Brand */}
      <Link
        href="/my-ai"
        style={{
          padding: "18px 16px",
          borderBottom: "1px solid var(--wg-line)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          textDecoration: "none",
          color: "var(--wg-ink)",
        }}
      >
        <img
          src="/brand/logo-mark.png"
          alt=""
          aria-hidden
          width={32}
          height={32}
          style={{
            width: 32,
            height: 32,
            borderRadius: "var(--wg-radius-sm)",
            objectFit: "contain",
          }}
        />
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            style={{
              fontSize: 16,
              fontFamily: "var(--wg-font-display)",
              fontWeight: 400,
              letterSpacing: "-0.01em",
            }}
          >
            GraphFlow
          </span>
          <span
            style={{
              fontSize: "var(--wg-fs-caption)",
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
          >
            v0.6.2
          </span>
        </span>
      </Link>

      {/* Primary nav — locked to the 5 surfaces. */}
      <nav
        aria-label="Primary"
        data-testid="primary-nav"
        style={{
          flex: 1,
          padding: "12px 8px",
          display: "flex",
          flexDirection: "column",
          gap: 2,
          overflowY: "auto",
        }}
      >
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.key}
              href={item.href}
              data-nav-key={item.key}
              style={{
                ...linkBase,
                ...(active ? linkActive : null),
              }}
            >
              <Icon size={18} strokeWidth={1.5} />
              <span>{t(`nav.${item.key}` as const)}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div
        style={{
          borderTop: "1px solid var(--wg-line)",
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 4,
          background: "var(--wg-surface-sunk)",
        }}
      >
        <Link
          href="/settings/profile"
          style={{
            ...linkBase,
            ...(isActive(pathname, "/settings/profile") ? linkActive : null),
            padding: "8px 10px",
          }}
        >
          <span
            aria-hidden
            style={{
              width: 26,
              height: 26,
              borderRadius: "50%",
              display: "grid",
              placeItems: "center",
              background: "var(--wg-accent-soft)",
              color: "var(--wg-accent)",
              fontSize: 11,
              fontWeight: 700,
              fontFamily: "var(--wg-font-mono)",
              flexShrink: 0,
            }}
          >
            {(user.display_name || user.username || "?").slice(0, 1).toUpperCase()}
          </span>
          <span
            style={{
              flex: 1,
              minWidth: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={user.display_name || user.username}
          >
            {user.display_name || user.username}
          </span>
          <UserIcon size={14} strokeWidth={1.5} />
        </Link>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            padding: "4px 10px",
          }}
        >
          <LanguageSwitcher />
          <form
            action="/api/auth/logout?redirect=/"
            method="POST"
            style={{ display: "inline" }}
          >
            <button
              type="submit"
              aria-label={t("drawer.close")}
              data-testid="sidebar-signout-v062"
              style={{
                background: "transparent",
                border: "none",
                color: "var(--wg-ink-soft)",
                cursor: "pointer",
                padding: 4,
                borderRadius: 6,
                display: "inline-flex",
                alignItems: "center",
              }}
            >
              <LogOut size={14} strokeWidth={1.5} />
            </button>
          </form>
        </div>
      </div>
    </aside>
  );
}
