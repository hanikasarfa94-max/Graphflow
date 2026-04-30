"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { listProjectRooms, type RoomSummary } from "@/lib/api";

const PRIMARY_TABS = [
  { slug: "", label: "Stream" },
  { slug: "status", label: "Status" },
  { slug: "settings", label: "Settings" },
];

const AUDIT_TABS = [
  { slug: "detail/graph", label: "Graph" },
  { slug: "detail/plan", label: "Plan" },
  { slug: "detail/clarify", label: "Clarify" },
  { slug: "detail/conflicts", label: "Conflicts" },
  { slug: "detail/events", label: "Events" },
  { slug: "detail/delivery", label: "Delivery" },
  { slug: "detail/im", label: "IM" },
];

export function ProjectNav({
  projectId,
  conflictBadge,
}: {
  projectId: string;
  conflictBadge?: number;
}) {
  const pathname = usePathname();

  const isAuditActive = pathname?.includes(`/projects/${projectId}/detail/`);
  const isRoomActive = pathname?.includes(`/projects/${projectId}/rooms/`);

  // Lazy-load rooms only after the user opens the flyout. Keeps the
  // primary stream view cheap; the rooms list is small and uncached.
  const [rooms, setRooms] = useState<RoomSummary[] | null>(null);
  const [roomsLoading, setRoomsLoading] = useState(false);
  function ensureRoomsLoaded() {
    if (rooms !== null || roomsLoading) return;
    setRoomsLoading(true);
    listProjectRooms(projectId)
      .then((r) => setRooms(r.rooms))
      .catch(() => setRooms([]))
      .finally(() => setRoomsLoading(false));
  }
  useEffect(() => {
    // If the URL already points at a room, prefetch the list so the
    // flyout opens immediately.
    if (isRoomActive) ensureRoomsLoaded();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRoomActive, projectId]);

  return (
    <nav
      style={{
        display: "flex",
        gap: 4,
        alignItems: "center",
        borderBottom: "1px solid var(--wg-line)",
      }}
      aria-label="project sections"
    >
      {PRIMARY_TABS.map((t) => {
        const href = t.slug
          ? `/projects/${projectId}/${t.slug}`
          : `/projects/${projectId}`;
        const active =
          pathname === href ||
          (t.slug === "" && pathname === `/projects/${projectId}`);
        return (
          <Link
            key={t.slug || "stream"}
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
          </Link>
        );
      })}

      <details
        onToggle={(e) => {
          if ((e.currentTarget as HTMLDetailsElement).open) ensureRoomsLoaded();
        }}
        style={{
          marginLeft: "auto",
          position: "relative",
          marginBottom: -1,
        }}
      >
        <summary
          style={{
            padding: "10px 14px",
            fontSize: 13,
            cursor: "pointer",
            listStyle: "none",
            color: isRoomActive ? "var(--wg-ink)" : "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
            borderBottom: isRoomActive
              ? "2px solid var(--wg-accent)"
              : "2px solid transparent",
            fontWeight: isRoomActive ? 600 : 400,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          Rooms
        </summary>
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            background: "#fff",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
            minWidth: 220,
            maxWidth: 320,
            padding: 4,
            zIndex: 20,
            display: "grid",
          }}
        >
          {rooms === null && roomsLoading && (
            <span
              style={{
                padding: "8px 12px",
                fontSize: 12,
                color: "var(--wg-ink-soft)",
              }}
            >
              Loading…
            </span>
          )}
          {rooms !== null && rooms.length === 0 && (
            <span
              style={{
                padding: "8px 12px",
                fontSize: 12,
                color: "var(--wg-ink-soft)",
              }}
            >
              No rooms yet
            </span>
          )}
          {rooms?.map((r) => {
            const href = `/projects/${projectId}/rooms/${r.id}`;
            const active = pathname === href;
            const memberCount = r.members?.length ?? 0;
            return (
              <Link
                key={r.id}
                href={href}
                aria-current={active ? "page" : undefined}
                style={{
                  padding: "8px 12px",
                  fontSize: 13,
                  textDecoration: "none",
                  color: active ? "var(--wg-ink)" : "var(--wg-ink-soft)",
                  fontWeight: active ? 600 : 400,
                  borderRadius: "var(--wg-radius)",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 6,
                }}
              >
                <span>{r.name ?? r.id.slice(0, 8)}</span>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--wg-ink-soft)",
                    fontFamily: "var(--wg-font-mono)",
                  }}
                >
                  {memberCount}p
                </span>
              </Link>
            );
          })}
        </div>
      </details>

      <details
        style={{
          position: "relative",
          marginBottom: -1,
        }}
      >
        <summary
          style={{
            padding: "10px 14px",
            fontSize: 13,
            cursor: "pointer",
            listStyle: "none",
            color: isAuditActive ? "var(--wg-ink)" : "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
            borderBottom: isAuditActive
              ? "2px solid var(--wg-accent)"
              : "2px solid transparent",
            fontWeight: isAuditActive ? 600 : 400,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          Audit
          {conflictBadge && conflictBadge > 0 ? (
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
        </summary>
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            background: "#fff",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
            minWidth: 180,
            padding: 4,
            zIndex: 20,
            display: "grid",
          }}
        >
          {AUDIT_TABS.map((t) => {
            const href = `/projects/${projectId}/${t.slug}`;
            const active = pathname === href;
            return (
              <Link
                key={t.slug}
                href={href}
                aria-current={active ? "page" : undefined}
                style={{
                  padding: "8px 12px",
                  fontSize: 13,
                  textDecoration: "none",
                  color: active ? "var(--wg-ink)" : "var(--wg-ink-soft)",
                  fontWeight: active ? 600 : 400,
                  borderRadius: "var(--wg-radius)",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 6,
                }}
              >
                <span>{t.label}</span>
                {t.slug === "detail/conflicts" &&
                conflictBadge &&
                conflictBadge > 0 ? (
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
        </div>
      </details>
    </nav>
  );
}
