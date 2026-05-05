"use client";

// SlashMenu — popover above the Composer that surfaces "rituals"
// (productized GraphFlow workflows) when the user types `/`.
//
// Design:
//   * Triggered when the textarea value starts with `/` (case-sensitive).
//   * Filters by the typed prefix (e.g. `/sa` → Save).
//   * Click or Enter selects; the parent Composer replaces the textarea
//     contents with the ritual's locale-appropriate template.
//   * Arrow keys move selection; Escape cancels (parent clears menu).
//
// The component is presentation-only — it does NOT mutate textarea
// state itself. The parent Composer owns the textarea and decides what
// to do on `onPick`.

import { useEffect, useMemo, useRef } from "react";
import { useLocale, useTranslations } from "next-intl";

import { filterRituals, type Ritual } from "@/lib/rituals";

type Props = {
  // The textarea's current value. We only render when it starts with `/`.
  // Pass the raw value so the menu sees keystroke filtering live.
  value: string;
  // 0-based selection index for keyboard arrow nav. Parent owns this so
  // it can wire keydown handlers on the textarea itself.
  selectedIndex: number;
  // Fires when the user picks a ritual (click or Enter). Parent should
  // expand the template and replace the textarea contents.
  onPick: (ritual: Ritual) => void;
  // Fires when the user moves the keyboard selection by clicking. Lets
  // the parent keep `selectedIndex` in sync with hover/click.
  onHover?: (index: number) => void;
};

export function SlashMenu({ value, selectedIndex, onPick, onHover }: Props) {
  const t = useTranslations("rituals");
  const tRoles = useTranslations("roles");
  const locale = useLocale();

  // The raw value may contain a space + arg (`/save foo`). For
  // filtering we only consider the leading word (the command itself).
  const firstToken = value.split(/\s/, 1)[0] ?? "";
  const filtered = useMemo(
    () => filterRituals(firstToken),
    [firstToken],
  );

  const listRef = useRef<HTMLDivElement | null>(null);

  // Keep the highlighted item visible when arrow-keying past the
  // viewport. Parent controls the index; we just scroll into view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLButtonElement>(
      `[data-ritual-idx="${selectedIndex}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!value.startsWith("/")) return null;

  const showEmpty = filtered.length === 0;

  return (
    <div
      data-testid="slash-menu"
      role="listbox"
      aria-label={t("menuTitle")}
      style={{
        position: "absolute",
        bottom: "calc(100% + 6px)",
        left: 0,
        right: 0,
        maxHeight: 320,
        overflowY: "auto",
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        boxShadow: "0 6px 18px rgba(0,0,0,0.08)",
        zIndex: 10,
      }}
      ref={listRef}
    >
      <div
        style={{
          padding: "8px 12px 6px 12px",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          color: "var(--wg-ink-soft)",
          borderBottom: "1px solid var(--wg-line)",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span>{t("menuTitle")}</span>
        <span style={{ fontSize: 10, textTransform: "none", letterSpacing: 0 }}>
          {t("menuHint")}
        </span>
      </div>

      {showEmpty ? (
        <div
          data-testid="slash-menu-empty"
          style={{
            padding: "12px",
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            fontStyle: "italic",
          }}
        >
          {t("noMatch")}
        </div>
      ) : (
        filtered.map((ritual, idx) => {
          const selected = idx === selectedIndex;
          return (
            <button
              key={ritual.id}
              type="button"
              role="option"
              aria-selected={selected}
              data-ritual-idx={idx}
              data-ritual-id={ritual.id}
              data-testid={`slash-item-${ritual.id}`}
              onClick={() => onPick(ritual)}
              onMouseEnter={() => onHover?.(idx)}
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr auto",
                alignItems: "center",
                gap: 10,
                width: "100%",
                padding: "8px 12px",
                background: selected
                  ? "var(--wg-accent-soft, rgba(21,91,213,0.06))"
                  : "transparent",
                border: "none",
                borderBottom: "1px solid var(--wg-line-faint, #f0f0f0)",
                textAlign: "left",
                cursor: "pointer",
                fontFamily: "var(--wg-font-sans)",
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 22,
                  textAlign: "center",
                  fontSize: 14,
                }}
              >
                {ritual.icon}
              </span>
              <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 8,
                    fontSize: 13,
                    color: "var(--wg-ink)",
                  }}
                >
                  <code
                    style={{
                      fontFamily: "var(--wg-font-mono)",
                      fontSize: 12,
                      color: "var(--wg-accent)",
                      background: "transparent",
                    }}
                  >
                    {ritual.command}
                  </code>
                  <span style={{ fontWeight: 500 }}>
                    {t(`${ritual.i18nKey}.label`)}
                  </span>
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: "var(--wg-ink-soft)",
                    lineHeight: 1.45,
                  }}
                >
                  {t(`${ritual.i18nKey}.hint`)}
                </span>
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontFamily: "var(--wg-font-mono)",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  color: "var(--wg-ink-soft)",
                  whiteSpace: "nowrap",
                }}
              >
                {tRoles(ritual.role)}
              </span>
            </button>
          );
        })
      )}

      {/* Arg hint for the highlighted ritual — helps the user see what
          the template's {arg} expects before they pick. Only renders
          when there's a selectable ritual + it carries an argHint. */}
      {!showEmpty && filtered[selectedIndex]?.argHint ? (
        <div
          data-testid="slash-menu-arghint"
          style={{
            padding: "6px 12px 10px 12px",
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
            background: "var(--wg-surface-subtle, #fafafa)",
          }}
        >
          {t("argHintPrefix")}{" "}
          {filtered[selectedIndex].argHint?.[locale === "zh" ? "zh" : "en"]}
        </div>
      ) : null}
    </div>
  );
}
