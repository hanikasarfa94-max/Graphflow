"use client";

// RehearsalPreview — pre-commit rehearsal card (vision.md §5.3).
//
// Rendered inline above the composer while the user is drafting. Shows
// how the edge sub-agent would classify the in-flight message if sent:
// answer / clarify / route_proposal. Silent kinds render nothing.
//
// States:
//   * loading          — "thinking…" spinner while the debounced fetch
//                        is in flight
//   * rate-limited     — muted cooldown hint; composer still works
//   * silent / silence — hidden (no card)
//   * answer           — muted "edge would answer" line
//   * clarify          — amber "edge would ask back" line
//   * route_proposal   — prominent "edge would route to X" with rationale
//
// The devil's-advocate line is surfaced from the EdgeResponse `reasoning`
// field when present, rendered with a ⚠ prefix in italics. EdgeAgent
// doesn't yet emit a dedicated devils-advocate channel, so this is a
// lightweight proxy — v2 can promote it to a first-class field.

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import type { RehearsalPreview as RehearsalPreviewType } from "@/lib/api";

type Props = {
  preview: RehearsalPreviewType | null;
  loading: boolean;
  rateLimited: boolean;
  // Team-stream uses a decorated shell (accent-soft eyebrow + "Send as-is"
  // footer, per north-star §pre-commit rehearsal). Personal stream passes
  // no handler and keeps the minimal v1 shell. Omitting this flag keeps
  // the two call sites visually distinct without duplicating the component.
  onSendAsIs?: () => void;
};

const BODY_PREVIEW_MAX = 180;

function truncate(body: string | null | undefined): string {
  if (!body) return "";
  if (body.length <= BODY_PREVIEW_MAX) return body;
  return body.slice(0, BODY_PREVIEW_MAX - 1).trimEnd() + "…";
}

export function RehearsalPreview({
  preview,
  loading,
  rateLimited,
  onSendAsIs,
}: Props) {
  const t = useTranslations("rehearsal");

  // When the team-stream caller passes onSendAsIs, wrap the body in an
  // accent-soft shell with mono eyebrow + "Send as-is" link. The shell is
  // subdued so it nudges, not shouts. We keep the inner bodies (answer /
  // clarify / route_proposal) visually consistent with the personal-stream
  // variant — only the surrounding chrome differs.
  const decorate = (inner: ReactNode) => {
    if (!onSendAsIs) return inner;
    return (
      <div
        style={{
          marginBottom: 8,
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          overflow: "hidden",
          // Keep motion minimal — opacity only, no slide-in. Browsers
          // honour prefers-reduced-motion here because we don't animate
          // transform or translate.
          transition: "opacity 120ms linear",
        }}
      >
        <div
          style={{
            padding: "4px 10px",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 10,
            letterSpacing: 0.4,
            textTransform: "uppercase",
            background: "var(--wg-accent-soft)",
            color: "var(--wg-ink-soft)",
            borderBottom: "1px solid var(--wg-line)",
          }}
        >
          {t("eyebrow")}
        </div>
        <div style={{ padding: "6px 10px 4px" }}>{inner}</div>
        <div
          style={{
            padding: "4px 10px 6px",
            textAlign: "right",
            borderTop: "1px solid var(--wg-line-soft, var(--wg-line))",
          }}
        >
          <button
            type="button"
            onClick={onSendAsIs}
            data-testid="rehearsal-send-as-is"
            style={{
              background: "transparent",
              border: "none",
              padding: 0,
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              color: "var(--wg-ink-soft)",
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            {t("sendAsIs")}
          </button>
        </div>
      </div>
    );
  };

  // Loading has priority: if we're actively fetching a preview, show the
  // thinking spinner. Rate-limited is a softer back-off state.
  if (loading) {
    return decorate(
      <div
        data-testid="rehearsal-preview"
        data-state="thinking"
        style={{
          marginBottom: onSendAsIs ? 0 : 8,
          padding: "6px 10px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          display: "flex",
          gap: 6,
          alignItems: "center",
        }}
      >
        <span
          aria-hidden
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            border: "2px solid var(--wg-ink-soft)",
            borderTopColor: "transparent",
            borderRadius: "50%",
            animation: "wg-spin 0.8s linear infinite",
          }}
        />
        <span>🧠 {t("thinking")}</span>
        <style>{`@keyframes wg-spin { to { transform: rotate(360deg); } }`}</style>
      </div>,
    );
  }

  if (rateLimited) {
    return decorate(
      <div
        data-testid="rehearsal-preview"
        data-state="cooldown"
        style={{
          marginBottom: onSendAsIs ? 0 : 8,
          padding: "6px 10px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
        }}
      >
        {t("cooldown")}
      </div>,
    );
  }

  if (!preview) return null;
  // Server-side short-circuit (draft < 10 chars) or LLM-chosen silence:
  // nothing to show. Composer stays clean.
  if (preview.kind === "silent_preview" || preview.kind === "silence") {
    return null;
  }

  const reasoning = preview.reasoning?.trim() || "";
  const devilsAdvocate = reasoning ? (
    <div
      style={{
        marginTop: 4,
        fontSize: 11,
        fontStyle: "italic",
        color: "var(--wg-ink-soft)",
      }}
    >
      ⚠ {reasoning}
    </div>
  ) : null;

  if (preview.kind === "answer") {
    return decorate(
      <div
        data-testid="rehearsal-preview"
        data-state="answer"
        style={{
          marginBottom: onSendAsIs ? 0 : 8,
          padding: onSendAsIs ? 0 : "8px 10px",
          fontSize: 12,
          background: onSendAsIs ? "transparent" : "var(--wg-surface)",
          border: onSendAsIs ? "none" : "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          color: "var(--wg-ink-soft)",
        }}
      >
        <div>
          🧠 {t("answer")}{" "}
          <em style={{ color: "var(--wg-ink)" }}>
            {truncate(preview.body)}
          </em>
        </div>
        {devilsAdvocate}
      </div>,
    );
  }

  if (preview.kind === "clarify") {
    return decorate(
      <div
        data-testid="rehearsal-preview"
        data-state="clarify"
        style={{
          marginBottom: onSendAsIs ? 0 : 8,
          padding: onSendAsIs ? 0 : "8px 10px",
          fontSize: 12,
          background: onSendAsIs
            ? "transparent"
            : "rgba(234, 179, 8, 0.08)",
          border: onSendAsIs
            ? "none"
            : "1px solid rgba(234, 179, 8, 0.35)",
          borderRadius: "var(--wg-radius)",
          color: "var(--wg-ink)",
        }}
      >
        <div>
          ❓ {t("clarify")}{" "}
          <em>{truncate(preview.body)}</em>
        </div>
        {devilsAdvocate}
      </div>,
    );
  }

  // route_proposal — the most prominent styling: this is the flag that
  // says "your message isn't actually for this stream; it wants Raj".
  const targets = preview.targets ?? [];
  const primary = targets[0];
  const targetName = primary?.display_name || primary?.username || "…";
  const rationale = primary?.rationale || "";

  return decorate(
    <div
      data-testid="rehearsal-preview"
      data-state="route_proposal"
      style={{
        marginBottom: onSendAsIs ? 0 : 8,
        padding: onSendAsIs ? 0 : "10px 12px",
        fontSize: 13,
        background: onSendAsIs
          ? "transparent"
          : "var(--wg-surface-raised, var(--wg-surface))",
        border: onSendAsIs ? "none" : "1px solid var(--wg-accent)",
        borderRadius: "var(--wg-radius)",
        color: "var(--wg-ink)",
      }}
    >
      <div>
        ↗{" "}
        {t.rich("routeProposal", {
          name: targetName,
          rationale,
          strong: (chunks) => <strong>{chunks}</strong>,
          em: (chunks) => <em>{chunks}</em>,
        })}
      </div>
      {preview.body && (
        <div
          style={{
            marginTop: 6,
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            fontStyle: "italic",
          }}
        >
          {truncate(preview.body)}
        </div>
      )}
      {devilsAdvocate}
    </div>,
  );
}
