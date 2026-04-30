"use client";

// Per-member skill tag editor. Shows the current chips; if the viewer
// can edit (self or project owner), exposes an inline editor.
//
// The membrane's task_promote review uses these tags to advise on
// assignee coverage at promote time. v0 vocabulary tracks
// TaskRow.assignee_role values; users may add free-form tags too.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ApiError, setMemberSkills } from "@/lib/api";

const SUGGESTED = [
  "pm",
  "frontend",
  "backend",
  "qa",
  "design",
  "business",
  "approver",
] as const;

export function SkillTagsControl({
  projectId,
  userId,
  initialTags,
  canEdit,
}: {
  projectId: string;
  userId: string;
  initialTags: string[];
  canEdit: boolean;
}) {
  const t = useTranslations("status.skills");
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [tags, setTags] = useState<string[]>(initialTags);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function add(raw: string) {
    const tag = raw.trim().toLowerCase().slice(0, 32);
    if (!tag || tags.includes(tag)) {
      setDraft("");
      return;
    }
    setTags([...tags, tag]);
    setDraft("");
  }

  function remove(tag: string) {
    setTags(tags.filter((x) => x !== tag));
  }

  async function save() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const r = await setMemberSkills(projectId, userId, tags);
      setTags(r.skill_tags);
      setEditing(false);
      router.refresh();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${t("saveFailed")} (${e.status})`
          : t("saveFailed"),
      );
    } finally {
      setPending(false);
    }
  }

  if (!editing) {
    return (
      <div
        data-testid="skill-tags"
        style={{
          marginTop: 4,
          display: "flex",
          flexWrap: "wrap",
          gap: 4,
          alignItems: "center",
        }}
      >
        {tags.length === 0 ? (
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
            }}
          >
            {t("noTags")}
          </span>
        ) : (
          tags.map((tag) => (
            <span
              key={tag}
              style={{
                padding: "1px 6px",
                borderRadius: 10,
                background: "var(--wg-surface-sunk)",
                border: "1px solid var(--wg-line)",
                fontSize: 10,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
              }}
            >
              {tag}
            </span>
          ))
        )}
        {canEdit ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            data-testid="skill-edit"
            style={{
              padding: "1px 6px",
              borderRadius: 10,
              background: "transparent",
              border: "1px dashed var(--wg-line)",
              color: "var(--wg-ink-soft)",
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              cursor: "pointer",
            }}
          >
            {t("edit")}
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div
      data-testid="skill-editor"
      style={{
        marginTop: 6,
        padding: 8,
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-sm, 4px)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {tags.map((tag) => (
          <button
            key={tag}
            type="button"
            onClick={() => remove(tag)}
            title={t("removeTag")}
            style={{
              padding: "1px 6px",
              borderRadius: 10,
              background: "var(--wg-surface)",
              border: "1px solid var(--wg-line)",
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink)",
              cursor: "pointer",
            }}
          >
            {tag} ×
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
          placeholder={t("placeholder")}
          maxLength={32}
          data-testid="skill-input"
          style={{
            flex: 1,
            padding: "2px 6px",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            background: "var(--wg-surface)",
            color: "var(--wg-ink)",
          }}
        />
        <button
          type="button"
          onClick={() => add(draft)}
          disabled={!draft.trim()}
          style={{
            padding: "2px 8px",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            background: "var(--wg-surface)",
            color: "var(--wg-ink)",
            cursor: "pointer",
          }}
        >
          {t("addTag")}
        </button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {SUGGESTED.filter((s) => !tags.includes(s)).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => add(s)}
            style={{
              padding: "1px 6px",
              borderRadius: 10,
              background: "transparent",
              border: "1px dashed var(--wg-line)",
              color: "var(--wg-ink-faint)",
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              cursor: "pointer",
            }}
          >
            + {s}
          </button>
        ))}
      </div>
      {error ? (
        <span
          role="alert"
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {error}
        </span>
      ) : null}
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setTags(initialTags);
            setDraft("");
            setError(null);
          }}
          disabled={pending}
          style={{
            padding: "2px 8px",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            background: "transparent",
            color: "var(--wg-ink)",
            cursor: "pointer",
          }}
        >
          {t("cancel")}
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={pending}
          style={{
            padding: "2px 8px",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            fontWeight: 600,
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            background: "var(--wg-accent)",
            color: "#fff",
            cursor: pending ? "progress" : "pointer",
          }}
        >
          {pending ? t("saving") : t("save")}
        </button>
      </div>
    </div>
  );
}
