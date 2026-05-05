"use client";

// Composer — v2 stream compose box.
//
// A growing textarea with paste-ingest for images (inlined as data URLs —
// no image-upload endpoint exists yet in v1, so we embed the data URL in
// the message body as a markdown-style token and let the renderer show
// it inline; see cards.tsx renderBodyWithAttachments). Plain text and
// URLs are inserted as-is.
//
// Optimistic update: the message renders immediately with a temporary id,
// then the WS echo supersedes it with the real row. If the POST fails we
// remove the optimistic row (onOptimisticError).
//
// Pre-commit rehearsal (vision.md §5.3): the parent can pass an
// `onPreview(body)` handler; we debounce the textarea value by
// PREVIEW_DEBOUNCE_MS after typing stops and fire the handler when the
// draft is ≥PREVIEW_MIN_BODY_LENGTH characters. The parent owns the
// RehearsalPreview render — we just surface the hook.
//
// Phase 2.A active membrane (vision §5.12): when the draft contains a
// http(s) URL we surface an inline "Ingest as signal" action that POSTs
// to /api/projects/{id}/membrane/paste. The action is a side-door — it
// does NOT send the draft as a message. Signals land status='pending-
// review' and still need human confirmation via the membrane card UX.

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocale, useTranslations } from "next-intl";

import { ApiError, api, extractApiErrorDetail, type IMMessage } from "@/lib/api";
import {
  expandRitual,
  filterRituals,
  type Ritual,
} from "@/lib/rituals";

import { getScopeTiers } from "./ScopeTierPills";
import { getStreamScope } from "./StreamContextPanel";
import { SlashMenu } from "./SlashMenu";
import { MESSAGE_BODY_MAX_LENGTH } from "./types";

// 500ms matches north-star §pre-commit rehearsal: long enough that typing
// bursts don't thrash the edge endpoint, short enough that users feel the
// card respond to each thought they finish.
const PREVIEW_DEBOUNCE_MS = 500;
const PREVIEW_MIN_BODY_LENGTH = 10;

// Imperative handle so a parent ("Send as-is" link on the rehearsal card)
// can flush the current draft. Only sendNow is exposed — the rest of
// composer state stays encapsulated.
export type ComposerHandle = {
  sendNow: () => void;
};

type Props = {
  projectId: string;
  currentUserId: string;
  onOptimisticSend: (m: IMMessage) => void;
  onOptimisticError: (optimisticId: string) => void;
  onError: (message: string | null) => void;
  // Optional pre-commit rehearsal hook — called on debounced keystroke
  // pauses when body.length >= PREVIEW_MIN_BODY_LENGTH. Parent decides
  // what to do (typically: fetch /preview and render RehearsalPreview).
  // The handler may be async; we don't block send on its result.
  onPreview?: (body: string) => void;
  // Parent signals that preview should clear (e.g. after send or when
  // the draft falls below the min length). If unset, the composer just
  // stops firing onPreview.
  onPreviewClear?: () => void;
  // Identifies which StreamContextPanel scope this composer should
  // attach to outgoing messages. When set, send() reads the latest
  // scope from localStorage (StreamContextPanel writes it there) and
  // includes it on the POST body. The backend may ignore the field
  // until the agent context-builder is wired through; until then this
  // is forward-compat scaffolding so the UI lever doesn't drift out
  // of sync with the wire.
  streamKey?: string;
  // Pickup #6 — when supplied, the message lands in this specific
  // stream (a room) instead of the project's team-room. Backend
  // validates membership; B3 chain auto-stamps room id on any
  // resulting decision crystallization. Existing personal-stream
  // composers omit this prop and keep posting to the team-room.
  streamId?: string;
  // Prototype port (App.tsx:256 plusMenu) — when supplied, renders a
  // `+` button to the left of the textarea that opens a small menu.
  // Caller wires the functional item (typically: submit-as-task →
  // POST /api/projects/{id}/tasks). Other vocabulary items render as
  // inert "coming soon" rows so the prototype's plus-menu shape lands
  // even before all four affordances exist.
  onSubmitAsTask?: (text: string) => Promise<void>;
};

const MAX_ROWS = 8;
const LINE_HEIGHT_PX = 20;

// Permissive URL extractor. Matches the server-side regex in
// services/membrane_ingest.py so the two sides agree on what counts
// as a paste-ingest candidate.
const URL_RE = /https?:\/\/[^\s<>"'[\]{}]+/i;

function extractFirstUrl(s: string): string | null {
  const m = s.match(URL_RE);
  return m ? m[0] : null;
}

export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  {
    projectId,
    currentUserId,
    onOptimisticSend,
    onOptimisticError,
    onError,
    onPreview,
    onPreviewClear,
    streamKey,
    streamId,
    onSubmitAsTask,
  },
  ref,
) {
  const t = useTranslations("stream");
  const tMembrane = useTranslations("membrane");
  const locale = useLocale();
  const [value, setValue] = useState("");
  const [posting, setPosting] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const [plusOpen, setPlusOpen] = useState(false);
  const [submittingTask, setSubmittingTask] = useState(false);
  // Slash menu — visible when the textarea starts with `/`. selection
  // tracks which ritual is highlighted for Enter / arrow nav. We clamp
  // to filtered.length-1 in the keydown handler so a backspace that
  // shrinks the filtered list doesn't leave the highlight pointing
  // past the end.
  const [slashIndex, setSlashIndex] = useState(0);
  const slashOpen = value.startsWith("/");
  // Reset highlight to the top whenever the open/close transition flips
  // — feels more natural than persisting the index across reopens.
  useEffect(() => {
    if (slashOpen) setSlashIndex(0);
  }, [slashOpen]);
  const filteredRituals = useMemo(() => {
    if (!slashOpen) return [];
    const firstToken = value.split(/\s/, 1)[0] ?? "";
    return filterRituals(firstToken);
  }, [slashOpen, value]);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pickRitual = useCallback(
    (ritual: Ritual) => {
      const expanded = expandRitual(ritual, "", locale === "zh" ? "zh" : "en");
      setValue(expanded);
      // Place the cursor at the {arg} slot (or end if the template has
      // no slot left) so the user types straight into it.
      requestAnimationFrame(() => {
        const ta = taRef.current;
        if (!ta) return;
        ta.focus();
        const slot = expanded.indexOf("{arg}");
        if (slot >= 0) {
          ta.setSelectionRange(slot, slot + "{arg}".length);
        } else {
          ta.setSelectionRange(expanded.length, expanded.length);
        }
        // Resize after content swap so we don't leave the box short.
        ta.style.height = "auto";
        ta.style.height = `${Math.min(
          ta.scrollHeight,
          LINE_HEIGHT_PX * MAX_ROWS + 20,
        )}px`;
      });
    },
    [locale],
  );

  const handleSubmitAsTask = useCallback(async () => {
    if (!onSubmitAsTask) return;
    const draft = value.trim();
    if (!draft) return;
    setSubmittingTask(true);
    try {
      await onSubmitAsTask(draft);
      setValue("");
      setPlusOpen(false);
      requestAnimationFrame(() => {
        const ta = taRef.current;
        if (ta) ta.style.height = "auto";
      });
    } catch (e) {
      onError(e instanceof Error ? e.message : "submit-as-task failed");
    } finally {
      setSubmittingTask(false);
    }
  }, [onSubmitAsTask, value, onError]);

  const detectedUrl = extractFirstUrl(value);

  // Debounce the preview fire so we don't hammer the endpoint while the
  // user is mid-type. Keep the effect isolated from autosize so a paste
  // triggering autosize doesn't reset the preview timer twice.
  useEffect(() => {
    if (!onPreview) return;
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
    const trimmed = value.trim();
    if (trimmed.length < PREVIEW_MIN_BODY_LENGTH) {
      // Tell the parent to clear any stale preview card so a short draft
      // doesn't leave "edge would route to X" up from a prior pause.
      onPreviewClear?.();
      return;
    }
    previewTimerRef.current = setTimeout(() => {
      onPreview(trimmed);
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      if (previewTimerRef.current) {
        clearTimeout(previewTimerRef.current);
        previewTimerRef.current = null;
      }
    };
  }, [value, onPreview, onPreviewClear]);

  // Grow the textarea up to MAX_ROWS. The scroll-inside behaviour kicks in
  // naturally because we cap the height and let the textarea's own overflow
  // take over.
  const autosize = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const max = LINE_HEIGHT_PX * MAX_ROWS + 20;
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`;
  }, []);

  const onPaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      // Images are pasted as data URLs — v1 has no upload endpoint, so we
      // embed the data URL directly. Documented v1 limitation in PLAN-v2 E.2.
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of Array.from(items)) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          e.preventDefault();
          const file = item.getAsFile();
          if (!file) continue;
          const reader = new FileReader();
          reader.onload = () => {
            const dataUrl = String(reader.result ?? "");
            if (!dataUrl) return;
            const token = `![image](${dataUrl})`;
            setValue((prev) => (prev ? `${prev}\n${token}` : token));
            requestAnimationFrame(autosize);
          };
          reader.readAsDataURL(file);
          return;
        }
      }
      // Plain text and URLs fall through to default paste. No URL auto-expand
      // in v1 — the text is inserted as-is.
    },
    [autosize],
  );

  async function beforeSend(_body: string): Promise<boolean> {
    // v2: pre-commit rehearsal lives here. For v1 we always proceed.
    return true;
  }

  async function send() {
    const body = value.trim();
    if (!body || posting) return;
    // A ritual template still showing the literal `{arg}` slot means
    // the user picked a ritual but hasn't filled in the argument yet.
    // Don't send the placeholder — just keep the textarea focused so
    // they can type. (No error toast — this is a "still drafting"
    // signal, not a failure.)
    if (body.includes("{arg}")) {
      taRef.current?.focus();
      return;
    }
    if (!(await beforeSend(body))) return;

    setPosting(true);
    onError(null);

    // Optimistic insert — tag with a pending id so we can remove it if the
    // POST fails. The WS echo from the server carries a real row; we dedup
    // by id in the StreamView reducer, so the pending row will simply be
    // superseded once the real one appears.
    const optimisticId = `pending-${crypto.randomUUID()}`;
    const optimistic: IMMessage = {
      id: optimisticId,
      project_id: projectId,
      author_id: currentUserId,
      body,
      created_at: new Date().toISOString(),
      suggestion: null,
    };
    onOptimisticSend(optimistic);
    setValue("");
    onPreviewClear?.();
    // Reset textarea height after clearing.
    requestAnimationFrame(autosize);

    try {
      const scope = streamKey ? getStreamScope(streamKey) : null;
      const scopeTiers = getScopeTiers(`project:${projectId}`);
      const payload = {
        body,
        ...(scope ? { scope } : {}),
        ...(scopeTiers ? { scope_tiers: scopeTiers } : {}),
        // Pickup #6: when the composer is mounted in a room view, send
        // the room's stream_id so the message lands there (not the
        // team-room) and any decision crystallization stamps the room
        // as scope_stream_id.
        ...(streamId ? { stream_id: streamId } : {}),
      };
      await api(`/api/projects/${projectId}/messages`, {
        method: "POST",
        body: payload,
      });
      // The WS frame will carry the real message — remove the optimistic
      // row so the real one can take its place. (The reducer dedups by id,
      // so the real row is additive.)
      onOptimisticError(optimisticId);
    } catch (e) {
      onOptimisticError(optimisticId);
      if (e instanceof ApiError) {
        if (e.status === 429) {
          onError("slow down — rate limited");
        } else if (e.status === 422 && body.length > MESSAGE_BODY_MAX_LENGTH) {
          // Belt-and-suspenders: the textarea has maxLength, but pasted
          // content can sometimes exceed it (browser inconsistency). Show
          // the friendly limit message instead of raw "error 422".
          onError(t("composer.tooLong", { max: MESSAGE_BODY_MAX_LENGTH }));
        } else {
          onError(extractApiErrorDetail(e.body) ?? `error ${e.status}`);
        }
      } else {
        onError("send failed");
      }
      // Put the body back so the user doesn't lose their typing.
      setValue(body);
    } finally {
      setPosting(false);
    }
  }

  // Expose sendNow to parents — "Send as-is" on the rehearsal card flushes
  // the current draft without the user having to move focus back. `send`
  // is recreated every render but useImperativeHandle captures the latest
  // closure, so the current `value` is always used.
  useImperativeHandle(ref, () => ({ sendNow: () => void send() }));

  async function ingestAsSignal() {
    if (!detectedUrl || ingesting) return;
    setIngesting(true);
    setIngestMessage(null);
    try {
      await api(`/api/projects/${projectId}/membrane/paste`, {
        method: "POST",
        body: { url: detectedUrl, note: value.trim() || null },
      });
      setIngestMessage(tMembrane("ingestSuccess"));
    } catch (e) {
      const fallback = tMembrane("ingestFailed");
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "message" in e.body
            ? String((e.body as { message?: unknown }).message ?? fallback)
            : fallback;
        setIngestMessage(detail);
      } else {
        setIngestMessage(fallback);
      }
    } finally {
      setIngesting(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {detectedUrl ? (
        <div
          data-testid="membrane-ingest-bar"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12,
            color: "var(--wg-muted, #666)",
            padding: "4px 8px",
            background: "var(--wg-surface-subtle, #f6f6f6)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
          }}
        >
          <span>{tMembrane("detectedUrl")}</span>
          <code
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              maxWidth: 280,
              flex: 1,
            }}
          >
            {detectedUrl}
          </code>
          <button
            type="button"
            onClick={() => void ingestAsSignal()}
            disabled={ingesting}
            data-testid="membrane-ingest-btn"
            style={{
              padding: "2px 10px",
              fontSize: 12,
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              background: "var(--wg-surface)",
              cursor: ingesting ? "wait" : "pointer",
            }}
          >
            {ingesting ? tMembrane("ingesting") : tMembrane("ingestAsSignal")}
          </button>
          {ingestMessage ? (
            <span style={{ color: "var(--wg-muted, #666)" }}>
              {ingestMessage}
            </span>
          ) : null}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", position: "relative" }}>
      {onSubmitAsTask && (
        <>
          <button
            type="button"
            data-testid="composer-plus"
            onClick={() => setPlusOpen((o) => !o)}
            aria-expanded={plusOpen}
            aria-label={t("composer.plusMenu.openLabel")}
            style={{
              alignSelf: "stretch",
              padding: "0 12px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              background: plusOpen
                ? "var(--wg-accent-soft)"
                : "var(--wg-surface)",
              color: "var(--wg-ink-soft)",
              fontSize: 18,
              cursor: "pointer",
              minWidth: 38,
            }}
          >
            +
          </button>
          {plusOpen && (
            <div
              data-testid="composer-plus-menu"
              role="menu"
              style={{
                position: "absolute",
                bottom: "calc(100% + 6px)",
                left: 0,
                minWidth: 220,
                padding: 6,
                background: "#fff",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius)",
                boxShadow: "0 6px 18px rgba(0,0,0,0.08)",
                zIndex: 10,
                display: "flex",
                flexDirection: "column",
                gap: 2,
              }}
            >
              <PlusMenuItem
                icon="📎"
                label={t("composer.plusMenu.uploadFile")}
                hint={t("composer.plusMenu.comingSoon")}
                disabled
              />
              <PlusMenuItem
                icon="🧩"
                label={t("composer.plusMenu.adjustContext")}
                hint={t("composer.plusMenu.adjustContextHint")}
                disabled
              />
              <PlusMenuItem
                icon="📨"
                label={t("composer.plusMenu.askPerson")}
                hint={t("composer.plusMenu.comingSoon")}
                disabled
              />
              <PlusMenuItem
                icon="✅"
                label={t("composer.plusMenu.submitAsTask")}
                onClick={() => void handleSubmitAsTask()}
                disabled={!value.trim() || submittingTask}
                testId="composer-submit-as-task"
              />
            </div>
          )}
        </>
      )}
      {slashOpen ? (
        <SlashMenu
          value={value}
          selectedIndex={Math.min(
            slashIndex,
            Math.max(0, filteredRituals.length - 1),
          )}
          onPick={pickRitual}
          onHover={(i) => setSlashIndex(i)}
        />
      ) : null}
      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          autosize();
        }}
        onKeyDown={(e) => {
          // Slash-menu keyboard handling. Only intercept when the menu
          // is open AND filtered list is non-empty — otherwise fall
          // through to the default send behaviour (Enter sends, etc.).
          if (slashOpen && filteredRituals.length > 0) {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setSlashIndex((i) => (i + 1) % filteredRituals.length);
              return;
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setSlashIndex((i) =>
                i === 0 ? filteredRituals.length - 1 : i - 1,
              );
              return;
            }
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              const idx = Math.min(slashIndex, filteredRituals.length - 1);
              const ritual = filteredRituals[idx];
              if (ritual) pickRitual(ritual);
              return;
            }
            if (e.key === "Escape") {
              e.preventDefault();
              setValue("");
              return;
            }
            if (e.key === "Tab") {
              e.preventDefault();
              const idx = Math.min(slashIndex, filteredRituals.length - 1);
              const ritual = filteredRituals[idx];
              if (ritual) pickRitual(ritual);
              return;
            }
          }
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void send();
          }
        }}
        onPaste={onPaste}
        placeholder={t("composer.placeholder")}
        rows={1}
        maxLength={MESSAGE_BODY_MAX_LENGTH}
        data-testid="stream-composer"
        style={{
          flex: 1,
          padding: "10px 12px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontSize: 14,
          fontFamily: "var(--wg-font-sans)",
          background: "var(--wg-surface)",
          resize: "none",
          lineHeight: `${LINE_HEIGHT_PX}px`,
          maxHeight: LINE_HEIGHT_PX * MAX_ROWS + 20,
          minHeight: LINE_HEIGHT_PX + 20,
          overflowY: "auto",
        }}
      />
      {/* Char counter only appears once the user is in the last 10% of the
          budget — silent until it matters. Mono font + ink-faint color so
          it doesn't compete with the message text. */}
      {value.length >= MESSAGE_BODY_MAX_LENGTH * 0.9 && (
        <span
          data-testid="composer-char-count"
          style={{
            alignSelf: "flex-end",
            marginBottom: 8,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color:
              value.length >= MESSAGE_BODY_MAX_LENGTH
                ? "var(--wg-accent)"
                : "var(--wg-ink-faint)",
            whiteSpace: "nowrap",
          }}
        >
          {t("composer.charCount", {
            count: value.length,
            max: MESSAGE_BODY_MAX_LENGTH,
          })}
        </span>
      )}
      <button
        type="button"
        onClick={() => void send()}
        disabled={!value.trim() || posting}
        data-testid="stream-send-btn"
        style={{
          padding: "10px 18px",
          background: "var(--wg-accent)",
          color: "#fff",
          border: "none",
          borderRadius: "var(--wg-radius)",
          fontSize: 14,
          fontWeight: 600,
          cursor: "pointer",
          opacity: !value.trim() || posting ? 0.6 : 1,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {posting && (
          <span
            aria-hidden
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              border: "2px solid #fff",
              borderTopColor: "transparent",
              borderRadius: "50%",
              animation: "wg-spin 0.8s linear infinite",
            }}
          />
        )}
        {t("actions.send")}
      </button>
      <style>{`@keyframes wg-spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    </div>
  );
});

function PlusMenuItem({
  icon,
  label,
  hint,
  onClick,
  disabled,
  testId,
}: {
  icon: string;
  label: string;
  hint?: string;
  onClick?: () => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      title={hint}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 10px",
        background: "transparent",
        border: "none",
        borderRadius: 4,
        textAlign: "left",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
        fontSize: 13,
        color: "var(--wg-ink)",
        fontFamily: "var(--wg-font-sans)",
      }}
    >
      <span aria-hidden style={{ fontSize: 14 }}>
        {icon}
      </span>
      <span>{label}</span>
    </button>
  );
}
