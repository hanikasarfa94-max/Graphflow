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
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";

import { ApiError, api, type IMMessage } from "@/lib/api";

import { getScopeTiers } from "./ScopeTierPills";
import { getStreamScope } from "./StreamContextPanel";

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
  },
  ref,
) {
  const t = useTranslations("stream");
  const tMembrane = useTranslations("membrane");
  const [value, setValue] = useState("");
  const [posting, setPosting] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
        } else {
          const detail =
            typeof e.body === "object" && e.body && "detail" in e.body
              ? String((e.body as { detail?: unknown }).detail ?? e.message)
              : `error ${e.status}`;
          onError(detail);
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
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
      <textarea
        ref={taRef}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          autosize();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void send();
          }
        }}
        onPaste={onPaste}
        placeholder={t("composer.placeholder")}
        rows={1}
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
