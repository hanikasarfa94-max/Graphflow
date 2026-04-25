"use client";

// Workspace invite affordance — owner/admin only. Same shape as
// InviteMemberSection (project invite), but POSTs to the workspace
// endpoint and supports a role dropdown (owner/admin/member/viewer).
//
// 404 on the user lookup → friendly "ask them to register first" copy.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  ApiError,
  inviteToWorkspace,
  type WorkspaceRole,
} from "@/lib/api";

const USERNAME_RE = /^[A-Za-z0-9_-]{3,32}$/;
const ROLE_OPTIONS: WorkspaceRole[] = ["member", "admin", "viewer"];
// "owner" intentionally NOT in the invite dropdown — promotion to
// owner happens via PATCH role after the user is in. Reduces the
// chance of a fat-fingered ownership grant during invite.

export function InviteToWorkspaceSection({ slug }: { slug: string }) {
  const t = useTranslations("workspace.invite");
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("member");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (pending) return;
    const u = username.trim();
    if (!USERNAME_RE.test(u)) {
      setError(t("invalidUsername"));
      return;
    }
    setPending(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await inviteToWorkspace(slug, { username: u, role });
      setSuccess(
        t("success", { name: res.display_name || res.username, role }),
      );
      setUsername("");
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { message?: unknown } | undefined;
        const code =
          body && typeof body.message === "string" ? body.message : "";
        if (code === "user_not_found") {
          setError(t("userNotFound", { name: u }));
        } else if (code === "forbidden") {
          setError(t("forbidden"));
        } else {
          setError(t("genericError", { code: code || `${err.status}` }));
        }
      } else {
        setError(t("networkError"));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <section
      data-testid="workspace-invite-section"
      style={{
        padding: "16px 18px",
        background: "var(--wg-surface-sunk)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-md)",
      }}
    >
      <h2
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          margin: "0 0 10px",
        }}
      >
        {t("title")}
      </h2>
      <form
        onSubmit={(e) => void handleSubmit(e)}
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder={t("usernamePlaceholder")}
          maxLength={32}
          data-testid="workspace-invite-username"
          style={{
            flex: "1 1 220px",
            padding: "8px 10px",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            background: "var(--wg-surface-raised)",
            color: "var(--wg-ink)",
            fontSize: 13,
            fontFamily: "var(--wg-font-body, inherit)",
          }}
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as WorkspaceRole)}
          data-testid="workspace-invite-role"
          style={{
            padding: "8px 10px",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            background: "var(--wg-surface-raised)",
            color: "var(--wg-ink)",
            fontSize: 13,
          }}
        >
          {ROLE_OPTIONS.map((r) => (
            <option key={r} value={r}>
              {t(`roleOption.${r}`)}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={pending}
          data-testid="workspace-invite-submit"
          style={{
            padding: "8px 14px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius-sm, 4px)",
            fontSize: 13,
            fontWeight: 600,
            cursor: pending ? "progress" : "pointer",
            opacity: pending ? 0.6 : 1,
          }}
        >
          {pending ? t("submitting") : t("submit")}
        </button>
      </form>
      {error ? (
        <div
          role="alert"
          style={{
            marginTop: 8,
            fontSize: 12,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </div>
      ) : null}
      {success ? (
        <div
          style={{
            marginTop: 8,
            fontSize: 12,
            color: "var(--wg-ok)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {success}
        </div>
      ) : null}
    </section>
  );
}
