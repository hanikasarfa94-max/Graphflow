"use client";

// InviteMemberSection — QA finding #1.
//
// Before this, the only way to invite a new member to a project was at
// creation time. The backend endpoint (POST /api/projects/{id}/invite)
// already accepts `{ "username": "..." }` and returns either
// `{ ok: true, user_id, username }` or HTTP 404 with
// `detail: "user_not_found"`. This component is the missing UI entry
// point.
//
// Rendered inside the project settings page, owner-gated. Non-owners
// still see the member list (so they can read the team) but not the
// invite form. The section pulls members from /api/projects/{id}/state
// on mount and refreshes in-place after a successful invite.
//
// Scope guard: this is invite-only. Role change / removal are
// deliberately not here — out of scope for the QA fix.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui";

type MemberRow = {
  user_id: string;
  username: string;
  display_name: string;
  role: string;
};

type ProjectStateLite = {
  members: MemberRow[];
};

type MeLite = { id: string };

type Props = {
  projectId: string;
};

// Matches the backend InviteRequest constraint + the username rule enforced
// on signup: 3–32 chars, alnum + underscore + dash. Keep in sync with
// apps/api/src/workgraph_api/routers/projects.py InviteRequest.
const USERNAME_RE = /^[A-Za-z0-9_-]+$/;

export function InviteMemberSection({ projectId }: Props) {
  const t = useTranslations("teamPage.invite");

  const [members, setMembers] = useState<MemberRow[]>([]);
  const [viewerId, setViewerId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [username, setUsername] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [successFor, setSuccessFor] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [state, me] = await Promise.all([
        api<ProjectStateLite>(`/api/projects/${projectId}/state`),
        api<MeLite>(`/api/auth/me`),
      ]);
      setMembers(state.members ?? []);
      setViewerId(me?.id ?? null);
    } catch (e) {
      setLoadError(
        e instanceof ApiError ? `load failed (${e.status})` : "load failed",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const isOwner = useMemo(() => {
    if (!viewerId) return false;
    const me = members.find((m) => m.user_id === viewerId);
    return me?.role === "owner";
  }, [members, viewerId]);

  function validate(u: string): string | null {
    if (u.length < 3 || u.length > 32) return t("errorBounds");
    if (!USERNAME_RE.test(u)) return t("errorChars");
    return null;
  }

  async function submit() {
    const u = username.trim();
    setSubmitError(null);
    setSuccessFor(null);
    const clientErr = validate(u);
    if (clientErr) {
      setSubmitError(clientErr);
      return;
    }
    if (members.some((m) => m.username === u)) {
      setSubmitError(t("errorAlreadyMember"));
      return;
    }
    setSubmitting(true);
    try {
      await api(`/api/projects/${projectId}/invite`, {
        method: "POST",
        body: { username: u },
      });
      setSuccessFor(u);
      setUsername("");
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // Backend shape: { detail: "user_not_found" } — match the QA
        // frustration: "No account found with username X".
        setSubmitError(t("errorNotFound", { username: u }));
      } else if (e instanceof ApiError && e.status === 403) {
        setSubmitError(t("errorForbidden"));
      } else {
        setSubmitError(
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
    <section
      data-testid="invite-member-section"
      style={{
        marginTop: 24,
        padding: 20,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      <h2 style={{ marginTop: 0 }}>{t("heading")}</h2>
      <p style={{ fontSize: 13, color: "var(--wg-ink-soft)", marginTop: 0 }}>
        {t("subtitle")}
      </p>

      {loadError ? (
        <p style={{ color: "var(--wg-accent)", fontSize: 13 }}>{loadError}</p>
      ) : null}

      {/* Member list — always visible to any viewer of the settings page. */}
      <div style={{ marginTop: 12 }}>
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: 6,
          }}
        >
          {t("membersLabel", { count: members.length })}
        </div>
        {loading ? (
          <p style={{ fontSize: 13, color: "var(--wg-ink-soft)" }}>…</p>
        ) : members.length === 0 ? (
          <p style={{ fontSize: 13, color: "var(--wg-ink-soft)" }}>
            {t("membersEmpty")}
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {members.map((m) => (
              <li
                key={m.user_id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "6px 0",
                  borderBottom: "1px solid var(--wg-line-soft)",
                  fontSize: 13,
                }}
              >
                <strong style={{ color: "var(--wg-ink)" }}>
                  {m.display_name}
                </strong>
                <span
                  style={{
                    fontFamily: "var(--wg-font-mono)",
                    fontSize: 11,
                    color: "var(--wg-ink-faint)",
                  }}
                >
                  @{m.username}
                </span>
                <span
                  style={{
                    marginLeft: "auto",
                    padding: "2px 8px",
                    borderRadius: 999,
                    background:
                      m.role === "owner"
                        ? "var(--wg-accent-soft)"
                        : "var(--wg-surface-sunk, var(--wg-surface-raised))",
                    color:
                      m.role === "owner"
                        ? "var(--wg-accent)"
                        : "var(--wg-ink-soft)",
                    fontFamily: "var(--wg-font-mono)",
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                  }}
                >
                  {m.role}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Invite form — owner only. */}
      {isOwner ? (
        <div
          style={{
            marginTop: 18,
            paddingTop: 14,
            borderTop: "1px solid var(--wg-line-soft)",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 8,
            }}
          >
            {t("formLabel")}
          </div>
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
                setSubmitError(null);
                setSuccessFor(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void submit();
                }
              }}
              placeholder={t("placeholder")}
              data-testid="invite-member-input"
              style={{
                flex: 1,
                minWidth: 200,
                padding: "6px 10px",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius)",
                fontSize: 14,
                fontFamily: "var(--wg-font-mono)",
                background: "var(--wg-surface)",
              }}
            />
            <Button
              variant="primary"
              onClick={() => void submit()}
              disabled={!username.trim() || submitting}
              data-testid="invite-member-submit"
            >
              {submitting ? t("submitting") : t("submit")}
            </Button>
          </div>
          {submitError ? (
            <p
              role="alert"
              data-testid="invite-member-error"
              style={{
                marginTop: 8,
                fontSize: 13,
                color: "var(--wg-accent)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {submitError}
            </p>
          ) : null}
          {successFor ? (
            <p
              role="status"
              data-testid="invite-member-success"
              style={{
                marginTop: 8,
                fontSize: 13,
                color: "var(--wg-ok, #2f8f4f)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t("success", { username: successFor })}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
