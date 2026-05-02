"use client";

// AgentComposer — Phase 2 message composer for the v-next shell.
//
// Layout matches prototype App.tsx:254-287 exactly:
//   [+] [plusMenu] [textarea]  [autoAgent toggle] [thinking select] [Send]
//
// Per spec §11:
//   E-6 (autoAgent toggle persistence) — client-side state only in v1
//   E-7 (thinking-mode hint plumbing)  — client-side state only in v1
//
// The toggle + select are rendered + persisted in localStorage but
// don't yet ride the wire to the backend. Real plumbing lands when
// PersonalStreamService.respond / POST /api/messages accept the hint.

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ApiError, postStreamMessage } from "@/lib/api";

import styles from "./AgentComposer.module.css";

interface Props {
  streamId: string;
  onSent?: () => void;
}

const PLUS_MENU_ITEMS = [
  { icon: "📎", labelKey: "plus.upload" },
  { icon: "🧩", labelKey: "plus.context" },
  { icon: "📨", labelKey: "plus.routePerson" },
  { icon: "✅", labelKey: "plus.submitTask" },
] as const;

export function AgentComposer({ streamId, onSent }: Props) {
  const t = useTranslations("shellVNext");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plusOpen, setPlusOpen] = useState(false);
  const [autoAgent, setAutoAgent] = useState(true);
  const [thinkingMode, setThinkingMode] = useState<"deep" | "fast">("deep");
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Restore client-side state per E-6 / E-7.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const a = window.localStorage.getItem("wg:vnext:autoAgent");
    if (a === "false") setAutoAgent(false);
    const m = window.localStorage.getItem("wg:vnext:thinking");
    if (m === "fast" || m === "deep") setThinkingMode(m);
  }, []);

  // Persist on change.
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("wg:vnext:autoAgent", autoAgent ? "true" : "false");
  }, [autoAgent]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("wg:vnext:thinking", thinkingMode);
  }, [thinkingMode]);

  // Focus textarea on stream change so user can immediately type.
  useEffect(() => {
    taRef.current?.focus();
    setBody("");
    setError(null);
  }, [streamId]);

  async function send() {
    const trimmed = body.trim();
    if (!trimmed || sending) return;
    setSending(true);
    setError(null);
    try {
      await postStreamMessage(streamId, trimmed);
      setBody("");
      setError(null);
      onSent?.();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${t("composerError")} (${err.status})`
          : t("composerError"),
      );
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className={styles.composer} data-testid="vnext-composer">
      <div className={styles.inner}>
        <div className={styles.plusWrapper}>
          <button
            type="button"
            className={styles.plus}
            onClick={() => setPlusOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={plusOpen}
            data-testid="vnext-composer-plus"
          >
            ＋
          </button>
          {plusOpen && (
            <div
              className={styles.plusMenu}
              role="menu"
              data-testid="vnext-composer-plus-menu"
            >
              {PLUS_MENU_ITEMS.map((item) => (
                <button
                  key={item.labelKey}
                  type="button"
                  role="menuitem"
                  className={styles.menuItem}
                  onClick={() => setPlusOpen(false)}
                >
                  <span aria-hidden>{item.icon}</span>
                  <span>{t(item.labelKey)}</span>
                </button>
              ))}
              <p className={styles.menuHint}>{t("plus.hint")}</p>
            </div>
          )}
        </div>

        <textarea
          ref={taRef}
          className={styles.input}
          rows={1}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t("composerPlaceholder")}
          data-testid="vnext-composer-input"
        />

        <label className={styles.autoAgent}>
          <span>{t("autoAgent")}</span>
          <button
            type="button"
            role="switch"
            aria-checked={autoAgent}
            className={`${styles.toggle} ${autoAgent ? styles.toggleOn : ""}`}
            onClick={() => setAutoAgent((v) => !v)}
            data-testid="vnext-composer-auto-agent"
          />
        </label>

        <select
          className={styles.select}
          value={thinkingMode}
          onChange={(e) =>
            setThinkingMode(e.target.value === "fast" ? "fast" : "deep")
          }
          aria-label={t("thinkingMode")}
          data-testid="vnext-composer-thinking"
        >
          <option value="deep">{t("thinking.deep")}</option>
          <option value="fast">{t("thinking.fast")}</option>
        </select>

        <button
          type="button"
          className={styles.send}
          onClick={() => void send()}
          disabled={!body.trim() || sending}
          data-testid="vnext-composer-send"
        >
          {sending ? t("composerSending") : t("composerSend")}
        </button>
      </div>
      {error && <div className={styles.errorLine}>{error}</div>}
    </div>
  );
}
