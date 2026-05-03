// Phase E — stream renderer types.
//
// MESSAGE_BODY_MAX_LENGTH must match the BE Pydantic constraint on
// MessageRequest.body. The FE uses it to set <textarea maxLength>, render
// the character counter, and show a friendly error when a 422 still slips
// through (e.g. paste of a >4000-char block in some browsers). If the BE
// limit changes, update here too.
export const MESSAGE_BODY_MAX_LENGTH = 4000;

// The team stream is a single timeline of polymorphic cards (north-star
// §"What the v2 surface actually is"). All cards share a timestamp and an
// id so the view can merge + sort them deterministically; the `kind`
// discriminator tells the renderer which card component to pick.
//
// Most kinds map 1:1 to backend rows we already have (IMMessage, IMSuggestion,
// Decision). AmbientSignalCard and CatchUpSummaryCard are scaffolded for v2 —
// we don't emit them yet, but the union is shaped so dropping them in later
// is additive.

import type { Decision, IMMessage, IMSuggestion } from "@/lib/api";

export type StreamMember = {
  user_id: string;
  username: string;
  display_name: string;
  role_in_stream?: string;
  // Optional — inferred from last_read_at on the backend; defaults to "online"
  // when unavailable. Tracked here so cards can render a presence dot.
  presence?: "online" | "away" | "offline";
};

export type StreamItem =
  | {
      kind: "human";
      id: string;
      created_at: string;
      message: IMMessage;
    }
  | {
      kind: "edge_llm";
      id: string;
      created_at: string;
      message: IMMessage;
      suggestion: IMSuggestion;
    }
  | {
      kind: "sub_agent";
      id: string;
      created_at: string;
      message: IMMessage;
      suggestion: IMSuggestion;
    }
  | {
      kind: "decision";
      id: string;
      created_at: string;
      decision: Decision;
      // When a decision is the result of a suggestion we already render above,
      // the parent message still gets a ⚡ badge. The standalone card is only
      // rendered when the decision has no in-stream parent (edit pipeline, etc.).
      parent_message_id: string | null;
    }
  | {
      kind: "ambient";
      id: string;
      created_at: string;
      label: string;
      detail?: string;
    }
  | {
      kind: "catch_up";
      id: string;
      created_at: string;
      summary: string;
    };

// The sub-agent attribution we show on a card depends on the suggestion kind.
// `kind: "none"` means IMAssist looked at the message but didn't propose
// anything — that renders as an edge-LLM "metabolized" turn, not a sub-agent.
export function attributionFor(sug: IMSuggestion): {
  kind: "edge" | "clarifier" | "decision" | "blocker";
  key: "edge" | "clarifier" | "decision" | "blocker";
} {
  if (sug.kind === "tag") return { kind: "clarifier", key: "clarifier" };
  if (sug.kind === "decision") return { kind: "decision", key: "decision" };
  if (sug.kind === "blocker") return { kind: "blocker", key: "blocker" };
  return { kind: "edge", key: "edge" };
}

// Relative timestamp — "2 min ago" style. Plain-text only; callers decide
// how to frame it (e.g. tooltip the absolute time on top).
export function relativeTime(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const diffMs = now - t;
  const sec = Math.max(0, Math.round(diffMs / 1000));
  if (sec < 45) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} hr ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

// Message-row timestamp — absolute clock time always inline, with the
// shortest date prefix that disambiguates. F.17 clock-system pass:
// chat messages need to show actual time (Slack/Lark rhythm), not
// relative buckets like "5 min ago" that vanish into "2d ago"
// quickly. The relative-time tooltip on hover is preserved by the
// caller via `title={...}` so callers retain access to the full
// absolute string for screen-reader / power users.
//
// Output by message age:
//   < today       → "14:30"
//   yesterday     → "Yesterday 14:30"
//   < 7 days      → "Mon 14:30"
//   older         → "Apr 22 14:30"
export function formatMessageTime(
  iso: string,
  now: number = Date.now(),
): string {
  const t = new Date(iso);
  if (!Number.isFinite(t.getTime())) return "";
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  const time = `${hh}:${mm}`;
  const today = new Date(now);
  const sameDay = t.toDateString() === today.toDateString();
  if (sameDay) return time;
  const yesterday = new Date(today.getTime() - 86_400_000);
  if (t.toDateString() === yesterday.toDateString()) {
    return `Yesterday ${time}`;
  }
  const daysDiff = (now - t.getTime()) / 86_400_000;
  if (daysDiff < 7) {
    return `${t.toLocaleDateString(undefined, { weekday: "short" })} ${time}`;
  }
  return `${t.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${time}`;
}

export function presenceDotColor(p?: StreamMember["presence"]): string {
  if (p === "away") return "var(--wg-amber)";
  if (p === "offline") return "var(--wg-ink-faint)";
  return "var(--wg-ok)";
}
