"use client";

// NotesSection — Phase V wiki UI for user-authored notes.
//
// Sits on /projects/[id]/kb above the existing membrane-tree browser
// and lists items the viewer can see (their personal + everyone's
// group). Inline "+ New note" form creates a personal-scope item by
// default; users can promote-to-group from each row when they're ready
// to share.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  createKbNote,
  deleteKbNote,
  demoteKbNote,
  listKbNotes,
  promoteKbNote,
  updateKbNote,
  uploadKbNote,
  type KbNote,
} from "@/lib/api";

export function NotesSection({
  projectId,
  currentUserId,
  isProjectOwner,
}: {
  projectId: string;
  currentUserId: string;
  isProjectOwner: boolean;
}) {
  const t = useTranslations("kbNotes");
  const [items, setItems] = useState<KbNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Hidden <input type=file> wired through a ref so the visible
  // "Upload file" button looks consistent with the rest of the chrome.
  const fileInputRef = useState<HTMLInputElement | null>(null);
  const setFileInput = (el: HTMLInputElement | null) => {
    fileInputRef[1](el);
  };

  async function handleFile(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      await uploadKbNote(projectId, { file });
      void refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        const body = e.body as { message?: unknown } | undefined;
        const code =
          body && typeof body.message === "string" ? body.message : "";
        if (code === "file_too_large" || e.status === 413) {
          setUploadError(t("uploadTooLarge"));
        } else if (code === "empty_file") {
          setUploadError(t("uploadEmpty"));
        } else {
          setUploadError(t("uploadFailed", { code: code || `${e.status}` }));
        }
      } else {
        setUploadError(t("uploadFailed", { code: "network" }));
      }
    } finally {
      setUploading(false);
    }
  }

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listKbNotes(projectId);
      setItems(r.items);
    } catch (e) {
      setError(e instanceof ApiError ? `error ${e.status}` : "load failed");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const personal = useMemo(
    () => items.filter((i) => i.scope === "personal"),
    [items],
  );
  const group = useMemo(
    () => items.filter((i) => i.scope === "group"),
    [items],
  );

  return (
    <section
      data-testid="kb-notes-section"
      style={{
        padding: "16px 18px",
        marginBottom: 18,
        background: "var(--wg-surface-sunk)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-md)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          {t("title")}
        </h3>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            ref={setFileInput}
            type="file"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                void handleFile(f);
                e.target.value = "";
              }
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef[0]?.click()}
            disabled={uploading}
            data-testid="kb-notes-upload-btn"
            style={{
              padding: "4px 12px",
              background: "transparent",
              color: "var(--wg-ink)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm, 4px)",
              fontSize: 12,
              fontWeight: 600,
              cursor: uploading ? "progress" : "pointer",
              opacity: uploading ? 0.6 : 1,
            }}
          >
            {uploading ? t("uploading") : t("uploadFile")}
          </button>
          <button
            type="button"
            onClick={() => setComposerOpen((v) => !v)}
            data-testid="kb-notes-new-btn"
            style={{
              padding: "4px 12px",
              background: composerOpen
                ? "var(--wg-line)"
                : "var(--wg-accent)",
              color: composerOpen ? "var(--wg-ink)" : "#fff",
              border: "none",
              borderRadius: "var(--wg-radius-sm, 4px)",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {composerOpen ? t("cancelNew") : t("newNote")}
          </button>
        </div>
      </header>

      {uploadError ? (
        <div
          role="alert"
          style={{
            padding: "6px 10px",
            marginBottom: 8,
            background: "var(--wg-accent-soft)",
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            fontSize: 12,
            color: "var(--wg-accent)",
          }}
        >
          {uploadError}
        </div>
      ) : null}

      {composerOpen ? (
        <NoteComposer
          projectId={projectId}
          onCreated={() => {
            setComposerOpen(false);
            void refresh();
          }}
          onCancel={() => setComposerOpen(false)}
        />
      ) : null}

      {error ? (
        <div
          role="alert"
          style={{
            padding: "6px 0",
            color: "var(--wg-accent)",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </div>
      ) : null}

      {loading ? (
        <div
          style={{
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
            padding: "6px 0",
          }}
        >
          {t("loading")}
        </div>
      ) : null}

      {!loading && items.length === 0 ? (
        <div
          style={{
            fontSize: 13,
            color: "var(--wg-ink-soft)",
            fontStyle: "italic",
            padding: "6px 0",
          }}
        >
          {t("empty")}
        </div>
      ) : null}

      {personal.length > 0 ? (
        <SubsectionList
          label={t("personalLabel")}
          items={personal}
          currentUserId={currentUserId}
          isProjectOwner={isProjectOwner}
          onChanged={refresh}
        />
      ) : null}
      {group.length > 0 ? (
        <SubsectionList
          label={t("groupLabel")}
          items={group}
          currentUserId={currentUserId}
          isProjectOwner={isProjectOwner}
          onChanged={refresh}
        />
      ) : null}
    </section>
  );
}

function NoteComposer({
  projectId,
  onCreated,
  onCancel,
}: {
  projectId: string;
  onCreated: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("kbNotes");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [scope, setScope] = useState<"personal" | "group">("personal");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (pending) return;
    if (!title.trim()) {
      setError(t("titleRequired"));
      return;
    }
    setPending(true);
    setError(null);
    try {
      await createKbNote(projectId, {
        title: title.trim(),
        content_md: content,
        scope,
      });
      onCreated();
    } catch (e) {
      setError(e instanceof ApiError ? `error ${e.status}` : "save failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      data-testid="kb-notes-composer"
      style={{
        padding: 12,
        marginBottom: 10,
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-sm, 4px)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t("titlePlaceholder")}
        maxLength={500}
        autoFocus
        style={inputStyle}
      />
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={t("contentPlaceholder")}
        rows={6}
        style={{ ...inputStyle, resize: "vertical", fontFamily: "var(--wg-font-mono)" }}
      />
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          fontSize: 12,
          color: "var(--wg-ink-soft)",
        }}
      >
        <label
          style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}
        >
          <input
            type="radio"
            checked={scope === "personal"}
            onChange={() => setScope("personal")}
          />
          {t("scopePersonal")}
        </label>
        <label
          style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}
        >
          <input
            type="radio"
            checked={scope === "group"}
            onChange={() => setScope("group")}
          />
          {t("scopeGroup")}
        </label>
        <span
          style={{
            color: "var(--wg-ink-faint)",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            marginLeft: "auto",
          }}
        >
          {scope === "group" ? t("scopeGroupHint") : t("scopePersonalHint")}
        </span>
      </div>
      {error ? (
        <div
          role="alert"
          style={{ fontSize: 12, color: "var(--wg-accent)" }}
        >
          {error}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="submit"
          disabled={pending}
          style={{
            padding: "6px 14px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius-sm, 4px)",
            fontSize: 12,
            fontWeight: 600,
            cursor: pending ? "progress" : "pointer",
          }}
        >
          {pending ? t("saving") : t("save")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          style={{
            padding: "6px 14px",
            background: "transparent",
            color: "var(--wg-ink)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {t("cancel")}
        </button>
      </div>
    </form>
  );
}

function SubsectionList({
  label,
  items,
  currentUserId,
  isProjectOwner,
  onChanged,
}: {
  label: string;
  items: KbNote[];
  currentUserId: string;
  isProjectOwner: boolean;
  onChanged: () => void;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {items.map((item) => (
          <NoteRow
            key={item.id}
            item={item}
            currentUserId={currentUserId}
            isProjectOwner={isProjectOwner}
            onChanged={onChanged}
          />
        ))}
      </ul>
    </div>
  );
}

function NoteRow({
  item,
  currentUserId,
  isProjectOwner,
  onChanged,
}: {
  item: KbNote;
  currentUserId: string;
  isProjectOwner: boolean;
  onChanged: () => void;
}) {
  const t = useTranslations("kbNotes");
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const isOwner = item.owner_user_id === currentUserId;
  const canEdit = isOwner || isProjectOwner;
  const canPromote = item.scope === "personal" && (isOwner || isProjectOwner);
  const canDemote = item.scope === "group" && isProjectOwner;

  async function doPromote() {
    if (busy) return;
    if (!confirm(t("promoteConfirm"))) return;
    setBusy("promote");
    try {
      await promoteKbNote(item.id);
      onChanged();
    } catch {
      /* swallow */
    } finally {
      setBusy(null);
    }
  }

  async function doDemote() {
    if (busy) return;
    setBusy("demote");
    try {
      await demoteKbNote(item.id);
      onChanged();
    } catch {
      /* swallow */
    } finally {
      setBusy(null);
    }
  }

  async function doDelete() {
    if (busy) return;
    if (!confirm(t("deleteConfirm"))) return;
    setBusy("delete");
    try {
      await deleteKbNote(item.id);
      onChanged();
    } catch {
      /* swallow */
    } finally {
      setBusy(null);
    }
  }

  return (
    <li
      data-testid="kb-note-row"
      data-scope={item.scope}
      style={{
        padding: "8px 10px",
        marginBottom: 4,
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-sm, 4px)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          style={{
            background: "transparent",
            border: "none",
            cursor: "pointer",
            padding: 0,
            fontSize: 13,
            fontWeight: 600,
            color: "var(--wg-ink)",
            flex: 1,
            textAlign: "left",
          }}
        >
          {item.title}
        </button>
        <span
          style={{
            fontSize: 10,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {item.source}
        </span>
        {canPromote ? (
          <button
            type="button"
            onClick={() => void doPromote()}
            disabled={busy !== null}
            style={ghostBtn}
          >
            {t("promote")}
          </button>
        ) : null}
        {canDemote ? (
          <button
            type="button"
            onClick={() => void doDemote()}
            disabled={busy !== null}
            style={ghostBtn}
          >
            {t("demote")}
          </button>
        ) : null}
        {canEdit ? (
          <button
            type="button"
            onClick={() => void doDelete()}
            disabled={busy !== null}
            style={{ ...ghostBtn, color: "var(--wg-accent)" }}
          >
            {t("delete")}
          </button>
        ) : null}
      </div>
      {item.attachment ? (
        <div
          style={{
            marginTop: 6,
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          <a
            href={item.attachment.download_url}
            download={item.attachment.filename}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="kb-note-download"
            style={{
              padding: "3px 8px",
              background: "var(--wg-surface-sunk)",
              color: "var(--wg-accent)",
              border: "1px solid var(--wg-accent-ring, var(--wg-accent))",
              borderRadius: 999,
              textDecoration: "none",
              fontWeight: 600,
            }}
          >
            ⬇ {item.attachment.filename}
          </a>
          <span style={{ color: "var(--wg-ink-faint)" }}>
            {formatBytes(item.attachment.bytes)} · {item.attachment.mime}
          </span>
        </div>
      ) : null}
      {expanded && item.content_md ? (
        <pre
          style={{
            marginTop: 8,
            padding: 10,
            background: "var(--wg-surface-sunk)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            whiteSpace: "pre-wrap",
            color: "var(--wg-ink)",
            maxHeight: 360,
            overflowY: "auto",
          }}
        >
          {item.content_md}
        </pre>
      ) : null}
    </li>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const inputStyle: React.CSSProperties = {
  padding: "6px 8px",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  fontSize: 13,
  fontFamily: "var(--wg-font-body, inherit)",
};

const ghostBtn: React.CSSProperties = {
  padding: "2px 8px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
};
