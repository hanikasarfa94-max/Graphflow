"use client";

// AgentComposer — Phase 3 message composer for the v-next shell.
//
// Layout matches prototype App.tsx:254-287:
//   [+] [plusMenu] [textarea]  [autoAgent toggle] [thinking select] [Send]
//
// Phase 3 wiring (per spec §11):
//   E-6 (autoAgent toggle) — server-persisted per-stream override via
//       /api/vnext/prefs. Default-on; the row only persists explicit
//       disables (matches BE semantics).
//   E-7 (thinking-mode hint) — server-persisted per-user preference
//       via the same endpoint. v1 stores the choice; the LLM-side
//       wire-through (model temperature / tier) is still deferred.
//   E-8 (project-inference suggestion) — when active stream is the
//       global 通用 Agent and the draft body case-insensitively
//       contains the title of one of the user's projects, show a
//       deterministic "open in Project X's agent" suggestion above
//       the textarea. Click switches the active stream via
//       onSuggestionAccept. LLM-based inference is the v2 upgrade
//       (flagged in code as TODO).

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  fetchMyProjects,
  fetchVNextPrefs,
  postStreamMessage,
  updateVNextPrefs,
  type ProjectSummary,
  type VNextThinkingMode,
} from "@/lib/api";

import styles from "./AgentComposer.module.css";

interface ProjectAgentForSuggestion {
  project_id: string;
  title: string;
  stream_id: string;
}

interface Props {
  streamId: string;
  // True when this composer is bound to the user's global 通用 Agent.
  // Drives E-8 keyword suggestion (only fires for the global stream).
  isGeneralAgent?: boolean;
  // Project-agent stream ids by project_id. Used by E-8 to map a
  // project-title match to the destination stream. Pass an empty list
  // when there are no project agents (the suggestion stays inert).
  projectAgents?: ProjectAgentForSuggestion[];
  // Switch the active stream to this id. Wired by AppShellClient.
  onSuggestionAccept?: (streamId: string) => void;
  onSent?: () => void;
}

const PLUS_MENU_ITEMS = [
  { icon: "📎", labelKey: "plus.upload" },
  { icon: "🧩", labelKey: "plus.context" },
  { icon: "📨", labelKey: "plus.routePerson" },
  { icon: "✅", labelKey: "plus.submitTask" },
] as const;

// E-8 deterministic match — substring (case-insensitive) of the project
// title in the draft body. A real LLM-based intent classifier is the v2
// upgrade; the spec calls this out as v1 explicitly out of scope.
function findKeywordMatch(
  body: string,
  candidates: ProjectAgentForSuggestion[],
): ProjectAgentForSuggestion | null {
  const trimmed = body.trim();
  if (trimmed.length < 3) return null;
  const lower = trimmed.toLowerCase();
  // Sort by title length descending so a longer title (more specific)
  // wins when one is a substring of another.
  const sorted = [...candidates].sort(
    (a, b) => b.title.length - a.title.length,
  );
  for (const c of sorted) {
    const t = c.title.trim();
    if (t.length < 2) continue;
    if (lower.includes(t.toLowerCase())) {
      return c;
    }
  }
  return null;
}

export function AgentComposer({
  streamId,
  isGeneralAgent = false,
  projectAgents = [],
  onSuggestionAccept,
  onSent,
}: Props) {
  const t = useTranslations("shellVNext");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plusOpen, setPlusOpen] = useState(false);
  const [autoAgent, setAutoAgent] = useState(true);
  const [thinkingMode, setThinkingMode] =
    useState<VNextThinkingMode>("deep");
  const [prefsHydrated, setPrefsHydrated] = useState(false);
  // Cached set of project agents fetched if the parent didn't pass them.
  // Keeps E-8 self-sufficient when the composer is rendered without the
  // shell's stream lists in scope.
  const [fallbackAgents, setFallbackAgents] = useState<
    ProjectAgentForSuggestion[]
  >([]);

  const taRef = useRef<HTMLTextAreaElement>(null);

  // Hydrate from /api/vnext/prefs on mount and whenever the active
  // stream changes (autoAgent is per-stream).
  useEffect(() => {
    let cancelled = false;
    fetchVNextPrefs()
      .then((p) => {
        if (cancelled) return;
        // Default-on: missing key means enabled.
        const disabled = p.auto_dispatch_streams[streamId] === false;
        setAutoAgent(!disabled);
        setThinkingMode(p.thinking_mode);
        setPrefsHydrated(true);
      })
      .catch(() => {
        if (cancelled) return;
        // Hydration failure is non-fatal — keep defaults and let the
        // user toggle. Persistence will retry on the next user action.
        setPrefsHydrated(true);
      });
    return () => {
      cancelled = true;
    };
  }, [streamId]);

  // Project-agents fallback fetch for E-8 when parent didn't supply.
  useEffect(() => {
    if (!isGeneralAgent || projectAgents.length > 0) return;
    let cancelled = false;
    fetchMyProjects()
      .then((ps: ProjectSummary[]) => {
        if (cancelled) return;
        // We only know project ids + titles from /api/projects; without
        // a stream id we can't redirect on click. Fall back to hiding
        // the suggestion when the parent doesn't supply mappings.
        // Keeping the fetch so a future endpoint that does include the
        // stream id can swap in here.
        setFallbackAgents(
          ps.map((p) => ({ project_id: p.id, title: p.title, stream_id: "" })),
        );
      })
      .catch(() => {
        // Silent — E-8 is opt-in polish, not load-bearing.
      });
    return () => {
      cancelled = true;
    };
  }, [isGeneralAgent, projectAgents.length]);

  // Focus textarea on stream change so user can immediately type.
  useEffect(() => {
    taRef.current?.focus();
    setBody("");
    setError(null);
  }, [streamId]);

  // E-8 — suggestion is computed from current draft + available project
  // agents. Only fires on the 通用 Agent surface; project-agent streams
  // already have the right context.
  const suggestion = useMemo(() => {
    if (!isGeneralAgent) return null;
    const candidates =
      projectAgents.length > 0 ? projectAgents : fallbackAgents;
    const haveStreamIds = candidates.some((c) => c.stream_id);
    if (!haveStreamIds) return null;
    return findKeywordMatch(body, candidates.filter((c) => c.stream_id));
  }, [body, isGeneralAgent, projectAgents, fallbackAgents]);

  async function persistAutoAgent(next: boolean) {
    setAutoAgent(next);
    try {
      await updateVNextPrefs({
        auto_dispatch: { stream_id: streamId, enabled: next },
      });
    } catch {
      // Non-fatal — leave the local toggle in the new state. The next
      // mount will reconcile from the server.
    }
  }

  async function persistThinkingMode(next: VNextThinkingMode) {
    setThinkingMode(next);
    try {
      await updateVNextPrefs({ thinking_mode: next });
    } catch {
      // Non-fatal.
    }
  }

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
      {suggestion && onSuggestionAccept && (
        <div
          className={styles.suggestion}
          data-testid="vnext-composer-suggestion"
          data-suggestion-stream-id={suggestion.stream_id}
        >
          <span aria-hidden>💡</span>
          <span className={styles.suggestionText}>
            {t("suggestion.label", { project: suggestion.title })}
          </span>
          <button
            type="button"
            className={styles.suggestionAccept}
            onClick={() => onSuggestionAccept(suggestion.stream_id)}
            data-testid="vnext-composer-suggestion-accept"
          >
            {t("suggestion.accept")}
          </button>
        </div>
      )}
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
            disabled={!prefsHydrated}
            className={`${styles.toggle} ${autoAgent ? styles.toggleOn : ""}`}
            onClick={() => void persistAutoAgent(!autoAgent)}
            data-testid="vnext-composer-auto-agent"
          />
        </label>

        <select
          className={styles.select}
          value={thinkingMode}
          disabled={!prefsHydrated}
          onChange={(e) =>
            void persistThinkingMode(
              e.target.value === "fast" ? "fast" : "deep",
            )
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
