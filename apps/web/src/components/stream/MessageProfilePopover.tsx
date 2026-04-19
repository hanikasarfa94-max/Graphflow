"use client";

// Phase H — "Message [name]" affordance.
//
// A compact button that, when clicked, calls POST /api/streams/dm to
// create-or-fetch the canonical 1:1 DM stream between the current user
// and the target, then navigates to `/streams/{id}`. Backend dedups by
// sorted member pair so repeat clicks on the same user land in the same
// stream.
//
// Surface: intended to render next to any avatar/name for a user who
// isn't the viewer. Variants:
//   - `button` (default) — a pill button with an icon + label
//   - `icon` — a chat bubble icon only (compact)
//
// Errors fall back to an inline status line instead of blowing up the
// parent; this is a minor affordance, not a primary flow.

import { useRouter } from "next/navigation";
import { useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { ApiError, createDMStream } from "@/lib/api";

type Variant = "button" | "icon";

type Props = {
  targetUserId: string;
  targetDisplayName?: string;
  variant?: Variant;
  // Optional — a parent that renders a popover/tooltip can intercept the
  // click instead of routing. Default behaviour is create-or-get + redirect.
  onBeforeNavigate?: () => void;
};

const baseBtn: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: "2px 8px",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  color: "var(--wg-ink-soft)",
  background: "transparent",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  cursor: "pointer",
  lineHeight: 1.4,
};

const iconBtn: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 24,
  height: 24,
  padding: 0,
  fontSize: 12,
  color: "var(--wg-ink-soft)",
  background: "transparent",
  border: "1px solid var(--wg-line)",
  borderRadius: "50%",
  cursor: "pointer",
};

export function MessageProfilePopover({
  targetUserId,
  targetDisplayName,
  variant = "button",
  onBeforeNavigate,
}: Props) {
  const t = useTranslations("dm");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go() {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      onBeforeNavigate?.();
      const res = await createDMStream(targetUserId);
      if (!res.ok || !res.stream?.id) {
        setErr("dm creation failed");
        return;
      }
      router.push(`/streams/${res.stream.id}`);
    } catch (e) {
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? e.message)
            : `error ${e.status}`;
        setErr(detail);
      } else {
        setErr("dm creation failed");
      }
    } finally {
      setBusy(false);
    }
  }

  const label = t("messagePerson");
  const ariaLabel = targetDisplayName
    ? `${label} ${targetDisplayName}`
    : label;

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={go}
        disabled={busy}
        aria-label={ariaLabel}
        title={ariaLabel}
        data-testid="dm-message-icon"
        style={{ ...iconBtn, opacity: busy ? 0.6 : 1 }}
      >
        <span aria-hidden>💬</span>
      </button>
    );
  }

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <button
        type="button"
        onClick={go}
        disabled={busy}
        aria-label={ariaLabel}
        data-testid="dm-message-btn"
        style={{ ...baseBtn, opacity: busy ? 0.6 : 1 }}
      >
        <span aria-hidden>💬</span>
        <span>{label}</span>
      </button>
      {err && (
        <span
          role="alert"
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {err}
        </span>
      )}
    </span>
  );
}
