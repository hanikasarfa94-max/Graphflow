"use client";

// Inline invite affordance hosted inside MembersPanel — adds a teammate
// where the team list lives, instead of forcing a trip to /settings.
// On success, calls router.refresh() so the server-rendered panel
// re-fetches /state and the new row appears in place.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui";

const USERNAME_RE = /^[A-Za-z0-9_-]+$/;

export function InlineMemberInvite({
  projectId,
  existingUsernames,
}: {
  projectId: string;
  existingUsernames: string[];
}) {
  const t = useTranslations("teamPage.invite");
  const router = useRouter();

  const [username, setUsername] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function validate(u: string): string | null {
    if (u.length < 3 || u.length > 32) return t("errorBounds");
    if (!USERNAME_RE.test(u)) return t("errorChars");
    return null;
  }

  async function submit() {
    const u = username.trim();
    setError(null);
    setSuccess(null);
    const clientErr = validate(u);
    if (clientErr) {
      setError(clientErr);
      return;
    }
    if (existingUsernames.includes(u)) {
      setError(t("errorAlreadyMember"));
      return;
    }
    setSubmitting(true);
    try {
      await api(`/api/projects/${projectId}/invite`, {
        method: "POST",
        body: { username: u },
      });
      setSuccess(t("success", { username: u }));
      setUsername("");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError(t("errorNotFound", { username: u }));
      } else if (e instanceof ApiError && e.status === 403) {
        setError(t("errorForbidden"));
      } else {
        setError(
          e instanceof ApiError
            ? t("errorGeneric", { status: e.status })
            : t("errorNetwork"),
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      style={{
        marginTop: 14,
        paddingTop: 14,
        borderTop: "1px solid var(--wg-line-soft)",
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <input
          type="text"
          value={username}
          onChange={(e) => {
            setUsername(e.target.value);
            setError(null);
            setSuccess(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder={t("placeholder")}
          aria-label={t("formLabel")}
          data-testid="inline-invite-input"
          style={{
            flex: 1,
            minWidth: 200,
            padding: "6px 10px",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            fontSize: 13,
            fontFamily: "var(--wg-font-mono)",
            background: "var(--wg-surface)",
          }}
        />
        <Button
          variant="primary"
          size="sm"
          onClick={() => void submit()}
          disabled={!username.trim() || submitting}
          data-testid="inline-invite-submit"
        >
          {submitting ? t("submitting") : t("submit")}
        </Button>
      </div>
      {error ? (
        <p
          role="alert"
          data-testid="inline-invite-error"
          style={{
            margin: "6px 0 0",
            fontSize: 12,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </p>
      ) : null}
      {success ? (
        <p
          role="status"
          data-testid="inline-invite-success"
          style={{
            margin: "6px 0 0",
            fontSize: 12,
            color: "var(--wg-ok, #2f8f4f)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {success}
        </p>
      ) : null}
    </div>
  );
}
