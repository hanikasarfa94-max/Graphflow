"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { slug: "", label: "Overview" },
  { slug: "graph", label: "Graph" },
  { slug: "plan", label: "Plan" },
  { slug: "conflicts", label: "Conflicts" },
  { slug: "delivery", label: "Delivery" },
  { slug: "clarify", label: "Clarify" },
  { slug: "im", label: "Chat" },
  { slug: "events", label: "Events" },
];

export function ProjectNav({
  projectId,
  conflictBadge,
}: {
  projectId: string;
  conflictBadge?: number;
}) {
  const pathname = usePathname();

  return (
    <nav
      style={{
        display: "flex",
        gap: 4,
        borderBottom: "1px solid var(--wg-line)",
      }}
      aria-label="project sections"
    >
      {TABS.map((t) => {
        const href = t.slug
          ? `/projects/${projectId}/${t.slug}`
          : `/projects/${projectId}`;
        const active =
          pathname === href ||
          (t.slug === "" && pathname === `/projects/${projectId}`);
        return (
          <Link
            key={t.slug}
            href={href}
            aria-current={active ? "page" : undefined}
            style={{
              padding: "10px 14px",
              fontSize: 14,
              textDecoration: "none",
              color: active ? "var(--wg-ink)" : "var(--wg-ink-soft)",
              borderBottom: active
                ? "2px solid var(--wg-accent)"
                : "2px solid transparent",
              marginBottom: -1,
              fontWeight: active ? 600 : 400,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {t.label}
            {t.slug === "conflicts" && conflictBadge && conflictBadge > 0 ? (
              <span
                aria-label={`${conflictBadge} open conflicts`}
                style={{
                  background: "var(--wg-accent)",
                  color: "#fff",
                  fontFamily: "var(--wg-font-mono)",
                  fontSize: 11,
                  fontWeight: 600,
                  padding: "1px 7px",
                  borderRadius: 10,
                  minWidth: 18,
                  textAlign: "center",
                }}
              >
                {conflictBadge}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
