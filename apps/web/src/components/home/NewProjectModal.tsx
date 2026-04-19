"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

// New-project modal per Phase F §7. Projects are created from the intake
// endpoint (POST /api/intake/message), which returns a project row. We
// then invite each supplied username via POST /api/projects/{id}/invite
// and navigate into the new project stream.
//
// Backend-fit notes:
//  * There's no separate "create project without description" endpoint
//    in v1 — intake treats the text as the first requirement, and uses
//    the title parameter if supplied. So we call intake with the user's
//    description (or the title verbatim if no description given) and
//    pass `title` when present.
//  * Invites happen post-create; partial failures surface as an inline
//    warning but don't block navigation to the new project.
export function NewProjectModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [invites, setInvites] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const titleRef = useRef<HTMLInputElement | null>(null);

  // Autofocus title + esc-to-close.
  useEffect(() => {
    if (!open) return;
    titleRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Reset on close so re-open starts fresh.
  useEffect(() => {
    if (!open) {
      setTitle("");
      setDescription("");
      setInvites("");
      setError(null);
      setWarning(null);
      setPending(false);
    }
  }, [open]);

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;
    setError(null);
    setWarning(null);
    setPending(true);
    try {
      // Intake accepts `text` (required) + `title`. We combine: text is the
      // description if given, otherwise the title itself so the row isn't
      // empty. The backend parses this as the first requirement.
      const text = description.trim() || trimmedTitle;
      const res = await fetch("/api/intake/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ text, title: trimmedTitle }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? t("home.newProject.errorCreate"));
        return;
      }
      const body = await res.json();
      const projectId: string | undefined =
        body?.project?.id ?? body?.project_id;
      if (!projectId) {
        setError(t("home.newProject.errorCreate"));
        return;
      }

      // Fire invites sequentially — a bad username here shouldn't block
      // the happy path. We surface failures as a warning under the form.
      const usernames = invites
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const failures: string[] = [];
      for (const username of usernames) {
        try {
          const ir = await fetch(`/api/projects/${projectId}/invite`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ username }),
          });
          if (!ir.ok) failures.push(username);
        } catch {
          failures.push(username);
        }
      }

      if (failures.length > 0) {
        setWarning(
          `${t("home.newProject.errorInvite")} ${failures.join(", ")}`,
        );
        // Give the user a moment to see the warning before navigating.
        setTimeout(() => router.push(`/projects/${projectId}`), 1500);
        return;
      }

      router.push(`/projects/${projectId}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("home.newProject.errorCreate"),
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-project-title"
      onMouseDown={(e) => {
        // Click-outside-to-close: only if the click started on the backdrop.
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20, 16, 10, 0.42)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        zIndex: 1000,
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: "min(520px, 100%)",
          background: "#fff",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          boxShadow: "0 10px 40px rgba(0,0,0,0.12)",
        }}
      >
        <h2
          id="new-project-title"
          style={{
            fontSize: 18,
            fontWeight: 600,
            margin: 0,
            letterSpacing: "-0.01em",
          }}
        >
          {t("home.newProject.title")}
        </h2>

        <Field label={t("home.newProject.titleLabel")}>
          <input
            ref={titleRef}
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t("home.newProject.titlePlaceholder")}
            required
            style={inputStyle}
          />
        </Field>

        <Field label={t("home.newProject.descriptionLabel")}>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder={t("home.newProject.descriptionPlaceholder")}
            style={{ ...inputStyle, resize: "vertical", minHeight: 70 }}
          />
        </Field>

        <Field label={t("home.newProject.inviteLabel")}>
          <input
            type="text"
            value={invites}
            onChange={(e) => setInvites(e.target.value)}
            placeholder={t("home.newProject.invitePlaceholder")}
            style={inputStyle}
          />
        </Field>

        {error ? (
          <div
            role="alert"
            style={{
              fontSize: 12,
              color: "var(--wg-accent)",
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            {error}
          </div>
        ) : null}
        {warning ? (
          <div
            role="status"
            style={{
              fontSize: 12,
              color: "var(--wg-amber)",
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            {warning}
          </div>
        ) : null}

        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            marginTop: 4,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            style={{
              padding: "8px 14px",
              background: "transparent",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              fontSize: 13,
              cursor: pending ? "not-allowed" : "pointer",
              color: "var(--wg-ink-soft)",
            }}
          >
            {t("home.newProject.cancel")}
          </button>
          <button
            type="submit"
            disabled={pending || !title.trim()}
            style={{
              padding: "8px 16px",
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--wg-radius)",
              fontSize: 13,
              fontWeight: 600,
              cursor: pending ? "progress" : "pointer",
              opacity: pending || !title.trim() ? 0.6 : 1,
            }}
          >
            {pending
              ? t("home.newProject.submitting")
              : t("home.newProject.submit")}
          </button>
        </div>
      </form>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 12px",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontFamily: "var(--wg-font-sans)",
  fontSize: 13,
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  boxSizing: "border-box",
};

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}
