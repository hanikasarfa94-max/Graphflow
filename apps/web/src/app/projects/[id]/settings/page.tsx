"use client";

// /projects/[id]/settings — v1 was a placeholder. Phase 2.A adds the
// "External signal subscriptions" section: owners manage the feeds +
// standing search queries that the active-membrane cron polls.
//
// Ingested content ALWAYS lands as MembraneSignalRow status='pending-
// review' regardless of source. Subscriptions only change *what* the
// membrane watches, not the trust contract.

import { use, useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { ApiError, api } from "@/lib/api";
import { GateKeeperMapSection } from "@/components/settings/GateKeeperMapSection";
import { InviteMemberSection } from "@/components/settings/InviteMemberSection";

type Subscription = {
  id: string;
  project_id: string;
  kind: "rss" | "search_query";
  url_or_query: string;
  active: boolean;
  last_polled_at: string | null;
  created_at: string | null;
};

type ListResponse = {
  ok: boolean;
  subscriptions: Subscription[];
};

export default function ProjectSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const tMembrane = useTranslations("membrane");
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"rss" | "search_query">("rss");
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanMsg, setScanMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<ListResponse>(
        `/api/projects/${id}/membrane/subscriptions`,
      );
      setSubs(res.subscriptions ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "error");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function addSub() {
    if (!value.trim() || submitting) return;
    setSubmitting(true);
    try {
      await api(`/api/projects/${id}/membrane/subscriptions`, {
        method: "POST",
        body: { kind, url_or_query: value.trim() },
      });
      setValue("");
      await refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "message" in e.body
            ? String((e.body as { message?: unknown }).message ?? "")
            : e.message;
        setError(detail || "error");
      } else {
        setError("error");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function removeSub(subId: string) {
    try {
      await api(
        `/api/projects/${id}/membrane/subscriptions/${subId}`,
        { method: "DELETE" },
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "error");
    }
  }

  async function scanNow() {
    setScanning(true);
    setScanMsg(null);
    try {
      const res = await api<{ ok: boolean; new_signals: number }>(
        `/api/projects/${id}/membrane/scan-now`,
        { method: "POST" },
      );
      setScanMsg(
        tMembrane("scanDone", { count: res.new_signals ?? 0 }),
      );
      await refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "message" in e.body
            ? String((e.body as { message?: unknown }).message ?? "")
            : e.message;
        setScanMsg(detail || "error");
      } else {
        setScanMsg("error");
      }
    } finally {
      setScanning(false);
    }
  }

  return (
    <main style={{ padding: 32, maxWidth: 800 }}>
      <h1 style={{ marginBottom: 24 }}>Settings</h1>

      <InviteMemberSection projectId={id} />

      <GateKeeperMapSection projectId={id} />

      <section
        id="membrane-subscriptions"
        data-testid="membrane-subscriptions"
        style={{
          marginTop: 24,
          padding: 20,
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          // Give the anchor-link jump target some breathing room from
          // the top so the browser scrolls the heading into view rather
          // than pinning it behind the sticky chrome.
          scrollMarginTop: 24,
        }}
      >
        <h2 style={{ marginTop: 0 }}>{tMembrane("subscriptionsHeading")}</h2>
        <p style={{ fontSize: 13, color: "var(--wg-muted, #666)" }}>
          {tMembrane("subscriptionsHelp")}
        </p>

        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            margin: "12px 0",
          }}
        >
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as typeof kind)}
            style={{
              padding: "6px 8px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
            }}
          >
            <option value="rss">{tMembrane("kindRss")}</option>
            <option value="search_query">
              {tMembrane("kindSearchQuery")}
            </option>
          </select>
          <input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={
              kind === "rss"
                ? tMembrane("rssPlaceholder")
                : tMembrane("searchPlaceholder")
            }
            style={{
              flex: 1,
              padding: "6px 10px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              fontSize: 14,
            }}
          />
          <button
            type="button"
            onClick={() => void addSub()}
            disabled={!value.trim() || submitting}
            style={{
              padding: "6px 12px",
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--wg-radius)",
              cursor: "pointer",
            }}
          >
            {tMembrane("addSubscription")}
          </button>
        </div>

        {error ? (
          <p style={{ color: "var(--wg-danger, #c00)", fontSize: 13 }}>
            {error}
          </p>
        ) : null}

        <div style={{ marginTop: 12 }}>
          {loading ? (
            <p>…</p>
          ) : subs.length === 0 ? (
            <p style={{ color: "var(--wg-muted, #666)", fontSize: 13 }}>
              {tMembrane("noSubscriptions")}
            </p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {subs.map((s) => (
                <li
                  key={s.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "8px 0",
                    borderBottom: "1px solid var(--wg-line)",
                  }}
                >
                  <span
                    style={{
                      fontSize: 11,
                      textTransform: "uppercase",
                      background: "var(--wg-surface-subtle, #f6f6f6)",
                      padding: "2px 6px",
                      borderRadius: 3,
                    }}
                  >
                    {s.kind === "rss"
                      ? tMembrane("kindRss")
                      : tMembrane("kindSearchQuery")}
                  </span>
                  <code
                    style={{
                      flex: 1,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      fontSize: 13,
                    }}
                  >
                    {s.url_or_query}
                  </code>
                  <button
                    type="button"
                    onClick={() => void removeSub(s.id)}
                    style={{
                      padding: "4px 10px",
                      fontSize: 12,
                      border: "1px solid var(--wg-line)",
                      borderRadius: "var(--wg-radius)",
                      background: "var(--wg-surface)",
                      cursor: "pointer",
                    }}
                  >
                    {tMembrane("removeSubscription")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div
          style={{
            marginTop: 20,
            display: "flex",
            gap: 12,
            alignItems: "center",
          }}
        >
          <button
            type="button"
            onClick={() => void scanNow()}
            disabled={scanning}
            style={{
              padding: "6px 14px",
              background: "var(--wg-surface)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              cursor: scanning ? "wait" : "pointer",
            }}
          >
            {scanning ? tMembrane("scanning") : tMembrane("scanNow")}
          </button>
          {scanMsg ? (
            <span style={{ fontSize: 13, color: "var(--wg-muted, #666)" }}>
              {scanMsg}
            </span>
          ) : null}
        </div>
      </section>
    </main>
  );
}
