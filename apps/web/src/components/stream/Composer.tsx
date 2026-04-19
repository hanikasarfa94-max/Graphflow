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

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ApiError, api, type IMMessage } from "@/lib/api";

const PREVIEW_DEBOUNCE_MS = 1000;
const PREVIEW_MIN_BODY_LENGTH = 10;

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
};

const MAX_ROWS = 8;
const LINE_HEIGHT_PX = 20;

export function Composer({
  projectId,
  currentUserId,
  onOptimisticSend,
  onOptimisticError,
  onError,
  onPreview,
  onPreviewClear,
}: Props) {
  const t = useTranslations("stream");
  const [value, setValue] = useState("");
  const [posting, setPosting] = useState(false);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      await api(`/api/projects/${projectId}/messages`, {
        method: "POST",
        body: { body },
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

  return (
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
  );
}
