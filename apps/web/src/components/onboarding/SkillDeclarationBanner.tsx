"use client";

// SkillDeclarationBanner — QA finding #9b.
//
// First-time soft prompt for members to declare 2–3 skills so the group
// knows where they fit. Rendered as a non-blocking inline banner at the
// top of the project stream (NOT a modal — modals kill the onboarding
// vibe per the QA note).
//
// Rules:
//   * Fires the first time a user lands on any project they're a member
//     of IF `user.profile.declared_abilities` is empty.
//   * Hides permanently after a successful PATCH /api/users/me.
//   * "Skip for now" stores a dismissal flag in localStorage keyed by
//     `skills-declared-skip-{userId}` so it doesn't re-pester them on
//     every project. It's a one-time prompt per user account, not per
//     project.
//   * Once the user declares abilities on any project, the banner stays
//     hidden everywhere — we re-check `/api/users/me` on each mount.
//
// No new backend endpoint needed: /api/users/me (GET + PATCH) already
// carries `profile.declared_abilities` per apps/api/src/workgraph_api/
// routers/users.py.

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui";

type Props = {
  projectId: string;
  projectTitle: string;
  userId: string;
};

type MeResponse = {
  id: string;
  username: string;
  display_name: string;
  profile?: {
    declared_abilities?: string[];
  } | null;
};

const LOCAL_STORAGE_PREFIX = "skills-declared-skip-";

// Split on comma / Chinese comma / semicolon / newline; trim; dedupe;
// cap at 8 so we don't send a list of 40 entries into the PATCH.
function parseSkills(raw: string): string[] {
  const parts = raw
    .split(/[,,;\n]/g)
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && s.length <= 40);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const p of parts) {
    const key = p.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(p);
    if (out.length >= 8) break;
  }
  return out;
}

export function SkillDeclarationBanner({
  projectId: _projectId,
  projectTitle,
  userId,
}: Props) {
  const t = useTranslations("skillDeclarationBanner");

  // `checking` means we haven't yet resolved the user's declared_abilities;
  // until then we render nothing so we don't flash the banner on users who
  // already declared. `visible` is the final render gate.
  const [checking, setChecking] = useState(true);
  const [visible, setVisible] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = useCallback(async () => {
    // Dismissed on this device? Don't bother hitting the API.
    try {
      const dismissed = window.localStorage.getItem(
        `${LOCAL_STORAGE_PREFIX}${userId}`,
      );
      if (dismissed === "1") {
        setVisible(false);
        setChecking(false);
        return;
      }
    } catch {
      // localStorage may throw on private-mode Safari; fall through.
    }

    try {
      const me = await api<MeResponse>(`/api/users/me`);
      const declared = me.profile?.declared_abilities ?? [];
      setVisible(declared.length === 0);
    } catch {
      // Silent: a failed probe should not trap the user under a banner.
      setVisible(false);
    } finally {
      setChecking(false);
    }
  }, [userId]);

  useEffect(() => {
    void decide();
  }, [decide]);

  async function save() {
    const skills = parseSkills(draft);
    if (skills.length === 0) {
      setError(t("errorEmpty"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api(`/api/users/me`, {
        method: "PATCH",
        body: { declared_abilities: skills },
      });
      setVisible(false);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? t("errorSave", { status: e.status })
          : t("errorNetwork"),
      );
    } finally {
      setSaving(false);
    }
  }

  function skip() {
    try {
      window.localStorage.setItem(`${LOCAL_STORAGE_PREFIX}${userId}`, "1");
    } catch {
      // same story — don't block dismissal if storage is unavailable.
    }
    setVisible(false);
  }

  if (checking || !visible) return null;

  return (
    <div
      data-testid="skill-declaration-banner"
      role="region"
      aria-label={t("heading", { project: projectTitle })}
      style={{
        margin: "0 0 12px",
        padding: "12px 14px",
        background: "var(--wg-accent-soft)",
        border: "1px solid var(--wg-accent-ring, var(--wg-accent))",
        borderRadius: "var(--wg-radius)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div>
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            marginBottom: 4,
          }}
        >
          {t("label")}
        </div>
        <div style={{ fontSize: 14, color: "var(--wg-ink)", lineHeight: 1.45 }}>
          {t("heading", { project: projectTitle })}
        </div>
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
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void save();
            }
          }}
          placeholder={t("placeholder")}
          data-testid="skill-declaration-input"
          style={{
            flex: 1,
            minWidth: 220,
            padding: "8px 10px",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            fontSize: 14,
            fontFamily: "var(--wg-font-sans)",
            background: "var(--wg-surface)",
          }}
        />
        <Button
          variant="primary"
          onClick={() => void save()}
          disabled={!draft.trim() || saving}
          data-testid="skill-declaration-save"
        >
          {saving ? t("saving") : t("save")}
        </Button>
        <Button
          variant="link"
          onClick={skip}
          disabled={saving}
          data-testid="skill-declaration-skip"
        >
          {t("skip")}
        </Button>
      </div>

      {error ? (
        <p
          role="alert"
          style={{
            margin: 0,
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
