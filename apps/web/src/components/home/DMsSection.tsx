import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { relativeTime } from "@/components/stream/types";

import type { HomeDMCard } from "./data";
import { SectionHeader } from "./SectionHeader";

const DM_DISPLAY_LIMIT = 10;

// DM list. Server component — no state needed. "+ New message" is left
// off for v1 (triggered from profile cards in project streams per
// north-star §"New-DM affordance"). If we add it here later, it would
// open a user-picker modal.
export async function DMsSection({ dms }: { dms: HomeDMCard[] }) {
  const t = await getTranslations();
  const visible = dms.slice(0, DM_DISPLAY_LIMIT);
  return (
    <section style={{ marginBottom: 40 }} aria-labelledby="home-dms">
      <SectionHeader title={t("home.dms.title")} />
      {visible.length === 0 ? (
        <div
          style={{
            padding: 16,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-faint)",
            fontSize: 13,
          }}
        >
          {t("home.dms.empty")}
        </div>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          {visible.map((d) => (
            <li key={d.stream_id}>
              <Link
                href={`/streams/${d.stream_id}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "36px 1fr auto",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 14px",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                  background: "var(--wg-surface-raised)",
                  textDecoration: "none",
                  color: "var(--wg-ink)",
                }}
              >
                <Avatar label={d.other_display_name} />
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: 14,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {d.other_display_name}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--wg-ink-faint)",
                      fontFamily: "var(--wg-font-mono)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {d.last_message_preview ?? t("home.dms.noLastMessage")}
                    {d.last_activity_at
                      ? ` · ${relativeTime(d.last_activity_at)}`
                      : ""}
                  </div>
                </div>
                {d.unread_count > 0 ? (
                  <span
                    style={{
                      background: "var(--wg-accent)",
                      color: "#fff",
                      fontSize: 11,
                      fontFamily: "var(--wg-font-mono)",
                      padding: "2px 8px",
                      borderRadius: 999,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t("home.unread.count", { count: d.unread_count })}
                  </span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Avatar({ label }: { label: string }) {
  const initial = (label || "?").trim().charAt(0).toUpperCase();
  return (
    <div
      aria-hidden
      style={{
        width: 36,
        height: 36,
        borderRadius: "50%",
        background: "var(--wg-surface-sunk)",
        color: "var(--wg-ink-soft)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontWeight: 600,
        fontSize: 14,
        fontFamily: "var(--wg-font-mono)",
        border: "1px solid var(--wg-line)",
      }}
    >
      {initial}
    </div>
  );
}
