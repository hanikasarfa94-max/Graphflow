"use client";

// UploadForm — Phase 2.B transcript paste + file picker.
//
// Two input modes, same submit:
//   * paste into a textarea (default) — for typed notes / copy-paste
//     out of Feishu Minutes export / Zoom panel.
//   * upload a .txt / .md / .srt / .vtt file — on pick, we read the
//     file as text, strip SRT/VTT timestamps with a minimal regex,
//     and drop the result into the textarea so the user can eyeball
//     it before submitting.
//
// SRT/VTT strip rule: any line that is either an SRT cue index
// (standalone integer), an SRT timestamp (HH:MM:SS,mmm --> ...), a
// VTT timestamp (HH:MM:SS.mmm --> ...), or the literal "WEBVTT"
// header is dropped. Everything else is kept verbatim and joined
// with single newlines. This is intentionally minimal — we don't
// reconstruct paragraphs or speaker labels; the metabolizer prompt
// handles that.

import { useRouter } from "next/navigation";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { useTranslations } from "next-intl";

import { Button, Text } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

// Drop any line that's a WEBVTT header, an SRT cue index, or a cue
// timestamp line (SRT or VTT shape). Keep everything else.
const _TIMESTAMP_LINE =
  /^\s*\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[.,]\d{3}.*$/;
const _CUE_INDEX_LINE = /^\s*\d+\s*$/;
const _WEBVTT_HEADER = /^WEBVTT\b/;

function stripTimestamps(text: string): string {
  const lines = text.split(/\r?\n/);
  const kept: string[] = [];
  for (const line of lines) {
    if (_WEBVTT_HEADER.test(line)) continue;
    if (_TIMESTAMP_LINE.test(line)) continue;
    if (_CUE_INDEX_LINE.test(line)) continue;
    kept.push(line);
  }
  return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function UploadForm({ projectId }: { projectId: string }) {
  const t = useTranslations("meeting");
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const buf = await file.text();
    const cleaned = /\.(srt|vtt)$/i.test(file.name)
      ? stripTimestamps(buf)
      : buf;
    setTranscript(cleaned);
    if (!title) {
      // Use the filename stem as a default title — user can still edit.
      const stem = file.name.replace(/\.[^.]+$/, "");
      setTitle(stem);
    }
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    const body = transcript.trim();
    if (body.length < 20) {
      setError(t("uploadTooShort"));
      return;
    }
    setSubmitting(true);
    try {
      await api(`/api/projects/${projectId}/meetings`, {
        method: "POST",
        body: {
          title: title.trim(),
          transcript_text: body,
          participant_user_ids: [],
        },
      });
      setTitle("");
      setTranscript("");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          (err.body as { message?: string } | null)?.message ||
            `upload_failed (${err.status})`,
        );
      } else {
        setError("upload_failed");
      }
    } finally {
      setSubmitting(false);
    }
  }

  const inputStyle = {
    width: "100%",
    padding: "8px 10px",
    fontSize: "var(--wg-fs-body)",
    fontFamily: "var(--wg-font-sans)",
    border: "1px solid var(--wg-line)",
    borderRadius: "var(--wg-radius)",
    background: "var(--wg-surface-raised)",
    color: "var(--wg-ink)",
    boxSizing: "border-box" as const,
  };

  return (
    <form
      onSubmit={onSubmit}
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Text variant="label" muted>
          {t("titleLabel")}
        </Text>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("titlePlaceholder")}
          maxLength={300}
          style={inputStyle}
        />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Text variant="label" muted>
          {t("fileLabel")}
        </Text>
        <input
          type="file"
          accept=".txt,.md,.srt,.vtt,text/plain"
          onChange={onFile}
          style={{ fontSize: 12 }}
        />
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Text variant="label" muted>
          {t("transcriptLabel")}
        </Text>
        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          rows={12}
          placeholder={t("transcriptPlaceholder")}
          style={{
            ...inputStyle,
            resize: "vertical" as const,
            minHeight: 200,
            fontFamily: "var(--wg-font-mono)",
          }}
        />
      </label>

      {error ? (
        <div role="alert">
          <Text variant="caption" style={{ color: "var(--wg-accent)" }}>
            {error}
          </Text>
        </div>
      ) : null}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button type="submit" variant="primary" disabled={submitting}>
          {submitting ? t("uploading") : t("uploadButton")}
        </Button>
      </div>
    </form>
  );
}
