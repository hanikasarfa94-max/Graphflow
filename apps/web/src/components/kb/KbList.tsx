"use client";

// /projects/[id]/kb list view (Phase Q.6).
//
// Client component because:
//   - Search is keystroke-interactive (300ms debounce → re-fetch)
//   - Filter chips mutate state and re-fetch
//
// Server-side initial data is handed in via `initialItems`, so the
// first paint is indexable and zero-delay. When either search or the
// filter chip changes, we re-hit the list endpoint with the new params.
// The debounced fetch ignores in-flight responses via an incrementing
// request id — classic stale-response guard.

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, listProjectKb, type KbItem } from "@/lib/api";

const FILTERS = ["all", "git", "steam", "rss", "user-drop"] as const;
type FilterKey = (typeof FILTERS)[number];

export function KbList({
  projectId,
  initialItems,
}: {
  projectId: string;
  initialItems: KbItem[];
}) {
  const t = useTranslations();
  const [items, setItems] = useState<KbItem[]>(initialItems);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reqIdRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runFetch = useCallback(
    async (q: string, f: FilterKey) => {
      const myId = ++reqIdRef.current;
      setLoading(true);
      setError(null);
      try {
        const res = await listProjectKb(projectId, {
          query: q,
          source_kind: f,
          limit: 50,
        });
        if (myId === reqIdRef.current) {
          setItems(res.items);
        }
      } catch (err) {
        if (myId === reqIdRef.current) {
          // 404 → backend endpoint hasn't shipped yet. Keep current
          // items; set a soft error so the UI shows "coming soon".
          if (err instanceof ApiError && err.status === 404) {
            setItems([]);
            setError("not-available");
          } else {
            setError(err instanceof Error ? err.message : "failed");
          }
        }
      } finally {
        if (myId === reqIdRef.current) {
          setLoading(false);
        }
      }
    },
    [projectId],
  );

  // Debounced keystroke search: 300ms after the user stops typing. We
  // *also* refetch immediately on filter-chip click — filter changes
  // are deliberate and shouldn't feel laggy.
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      runFetch(query, filter);
    }, 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query, filter, runFetch]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t("kb.search")}
        aria-label={t("kb.search")}
        style={{
          width: "100%",
          padding: "10px 12px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontSize: 14,
          fontFamily: "inherit",
          background: "#fff",
          color: "var(--wg-ink)",
          boxSizing: "border-box",
        }}
      />

      <div
        role="tablist"
        aria-label={t("kb.title")}
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        {FILTERS.map((f) => {
          const active = filter === f;
          return (
            <button
              key={f}
              role="tab"
              aria-selected={active}
              onClick={() => setFilter(f)}
              style={{
                padding: "4px 12px",
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
                border: "1px solid var(--wg-line)",
                background: active ? "var(--wg-ink)" : "#fff",
                color: active ? "#fff" : "var(--wg-ink)",
                borderRadius: 999,
                cursor: "pointer",
              }}
            >
              {t(`kb.filters.${f}`)}
            </button>
          );
        })}
        {loading ? (
          <span
            style={{
              alignSelf: "center",
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              marginLeft: 8,
            }}
          >
            {t("states.loading")}
          </span>
        ) : null}
      </div>

      {error === "not-available" ? (
        <EmptyState>{t("kb.notAvailable")}</EmptyState>
      ) : error ? (
        <div
          role="alert"
          style={{
            padding: 12,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 13,
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius)",
          }}
        >
          {error}
        </div>
      ) : items.length === 0 ? (
        <EmptyState>{t("kb.empty")}</EmptyState>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "grid",
            gap: 10,
          }}
        >
          {items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/projects/${projectId}/kb/${item.id}`}
                style={{
                  display: "block",
                  padding: "12px 14px",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                  background: "#fff",
                  color: "var(--wg-ink)",
                  textDecoration: "none",
                }}
              >
                <KbListRow item={item} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function KbListRow({ item }: { item: KbItem }) {
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 4,
          flexWrap: "wrap",
        }}
      >
        <SourceBadge kind={item.source_kind} />
        {item.ingested_by_username ? (
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            @{item.ingested_by_username}
          </span>
        ) : null}
        <span
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            marginLeft: "auto",
          }}
        >
          {relativeTime(item.created_at)}
        </span>
      </div>
      <div
        style={{
          fontSize: 14,
          color: "var(--wg-ink)",
          lineHeight: 1.45,
          display: "-webkit-box",
          WebkitBoxOrient: "vertical",
          WebkitLineClamp: 3,
          overflow: "hidden",
        }}
      >
        {item.summary || "(no summary)"}
      </div>
      {item.tags && item.tags.length > 0 ? (
        <div
          style={{
            marginTop: 6,
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
          }}
        >
          {item.tags.slice(0, 8).map((tag) => (
            <span
              key={tag}
              style={{
                fontSize: 10,
                fontFamily: "var(--wg-font-mono)",
                padding: "1px 6px",
                background: "var(--wg-surface)",
                border: "1px solid var(--wg-line)",
                borderRadius: 10,
                color: "var(--wg-ink-soft)",
              }}
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </>
  );
}

function SourceBadge({ kind }: { kind: string }) {
  const normalized = (kind || "").toLowerCase();
  return (
    <span
      style={{
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        padding: "2px 8px",
        borderRadius: 10,
        background: "var(--wg-ink)",
        color: "#fff",
        letterSpacing: "0.04em",
        textTransform: "uppercase",
      }}
    >
      {normalized || "unknown"}
    </span>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: "24px 16px",
        color: "var(--wg-ink-soft)",
        fontSize: 13,
        textAlign: "center",
        border: "1px dashed var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      {children}
    </div>
  );
}

// Minimal relative-time formatter. Intentionally not i18n'd here because
// the list view needs density; if we need localized "2 hours ago" strings
// later, swap in the shared age helpers.
function relativeTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const delta = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  if (delta < 86400 * 30) return `${Math.floor(delta / 86400)}d ago`;
  return new Date(t).toLocaleDateString();
}
