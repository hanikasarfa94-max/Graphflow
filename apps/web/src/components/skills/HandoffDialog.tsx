"use client";

// HandoffDialog — Stage 3 skill succession UI.
//
// Opened from the skill atlas page on owner-view. Lets the owner pick a
// successor, draft the handoff (derives PII-stripped routines on the
// server), preview the brief, and finalize. Finalization activates the
// routine layer — from that point, the successor's inherited routines
// show up in /api/projects/{id}/handoffs/for/{user_id}.
//
// Kept intentionally minimal: inline modal, no router manipulation,
// parent refreshes the atlas state (or not) when the dialog closes.

import { useMemo, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  finalizeHandoff,
  prepareHandoff,
  type HandoffRecord,
  type SkillAtlasMemberCard,
} from "@/lib/api";

type Props = {
  projectId: string;
  departingMember: SkillAtlasMemberCard;
  candidates: SkillAtlasMemberCard[];
  onClose: () => void;
};

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(15, 18, 22, 0.48)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
  padding: 20,
};

const panelStyle: CSSProperties = {
  width: "min(720px, 100%)",
  maxHeight: "min(90vh, 820px)",
  overflow: "auto",
  background: "var(--wg-surface-raised)",
  border: "1px solid var(--wg-line)",
  borderRadius: 10,
  padding: "22px 24px",
  fontFamily: "var(--wg-font-sans)",
  color: "var(--wg-ink)",
  display: "flex",
  flexDirection: "column",
  gap: 14,
};

const labelStyle: CSSProperties = {
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--wg-ink-faint)",
};

export function HandoffDialog({
  projectId,
  departingMember,
  candidates,
  onClose,
}: Props) {
  const t = useTranslations("skillAtlas.handoff");
  const [successorId, setSuccessorId] = useState<string>("");
  const [draft, setDraft] = useState<HandoffRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);

  const candidateList = useMemo(
    () =>
      candidates.filter((c) => c.user_id !== departingMember.user_id),
    [candidates, departingMember.user_id],
  );

  async function handlePrepare() {
    if (!successorId || preparing) return;
    setError(null);
    setPreparing(true);
    try {
      const res = await prepareHandoff(
        projectId,
        departingMember.user_id,
        successorId,
      );
      setDraft(res.handoff);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? "")
            : `error ${e.status}`
          : t("prepareFailed"),
      );
    } finally {
      setPreparing(false);
    }
  }

  async function handleFinalize() {
    if (!draft || finalizing) return;
    setFinalizing(true);
    try {
      const res = await finalizeHandoff(draft.id);
      setDraft(res.handoff);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `error ${e.status}`
          : "finalize failed",
      );
    } finally {
      setFinalizing(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={overlayStyle}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div style={panelStyle}>
        <header>
          <h2
            style={{
              margin: 0,
              fontSize: 20,
              fontWeight: 600,
            }}
          >
            {t("dialogTitle", { name: departingMember.display_name })}
          </h2>
          <p
            style={{
              margin: "8px 0 0",
              fontSize: 13,
              color: "var(--wg-ink-soft)",
              lineHeight: 1.55,
            }}
          >
            {t("dialogSubtitle")}
          </p>
        </header>

        {!draft ? (
          <section
            style={{ display: "flex", flexDirection: "column", gap: 10 }}
          >
            <label style={labelStyle}>{t("successorLabel")}</label>
            <select
              value={successorId}
              onChange={(e) => setSuccessorId(e.target.value)}
              style={{
                padding: "8px 10px",
                border: "1px solid var(--wg-line)",
                borderRadius: 6,
                fontFamily: "var(--wg-font-sans)",
                fontSize: 13,
                background: "var(--wg-surface)",
                color: "var(--wg-ink)",
              }}
            >
              <option value="">{t("successorPlaceholder")}</option>
              {candidateList.map((c) => (
                <option key={c.user_id} value={c.user_id}>
                  {c.display_name} ·{" "}
                  {c.role_hints[0] ?? c.project_role}
                </option>
              ))}
            </select>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <button
                type="button"
                onClick={() => void handlePrepare()}
                disabled={!successorId || preparing}
                style={primaryButton(preparing)}
              >
                {preparing ? t("preparing") : t("prepareButton")}
              </button>
              <button
                type="button"
                onClick={onClose}
                style={secondaryButton()}
              >
                {t("cancel")}
              </button>
            </div>
          </section>
        ) : (
          <section
            style={{ display: "flex", flexDirection: "column", gap: 12 }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
              }}
            >
              <span style={labelStyle}>{t("draftHeader")}</span>
              <StatusChip
                status={draft.status}
                labelDraft={t("statusDraft")}
                labelFinalized={t("statusFinalized")}
              />
            </div>

            <div>
              <h3
                style={{
                  margin: "0 0 6px",
                  fontSize: 12,
                  fontFamily: "var(--wg-font-mono)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: "var(--wg-ink-faint)",
                }}
              >
                {t("roleSkillsHeader")}
              </h3>
              {draft.role_skills_transferred.length > 0 ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {draft.role_skills_transferred.map((s) => (
                    <Chip key={s} label={s} tone="role" />
                  ))}
                </div>
              ) : (
                <em style={mutedText}>—</em>
              )}
            </div>

            <div>
              <h3
                style={{
                  margin: "0 0 6px",
                  fontSize: 12,
                  fontFamily: "var(--wg-font-mono)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: "var(--wg-ink-faint)",
                }}
              >
                {t("routinesHeader")}
              </h3>
              {draft.profile_skill_routines.length > 0 ? (
                <ul
                  style={{
                    margin: 0,
                    padding: 0,
                    listStyle: "none",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  {draft.profile_skill_routines.map((r) => (
                    <li
                      key={r.skill}
                      style={{
                        padding: "8px 10px",
                        background: "var(--wg-surface)",
                        border: "1px solid var(--wg-line-soft, var(--wg-line))",
                        borderRadius: 6,
                        fontSize: 13,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          marginBottom: 4,
                        }}
                      >
                        <code
                          style={{
                            fontFamily: "var(--wg-font-mono)",
                            fontSize: 12,
                            color: "var(--wg-accent)",
                          }}
                        >
                          {r.skill}
                        </code>
                        <span
                          style={{
                            fontFamily: "var(--wg-font-mono)",
                            fontSize: 11,
                            color: "var(--wg-ink-faint)",
                          }}
                        >
                          {t("evidenceCount", { n: r.evidence_count })}
                        </span>
                      </div>
                      <div
                        style={{
                          color: "var(--wg-ink-soft)",
                          lineHeight: 1.5,
                        }}
                      >
                        {r.summary}
                      </div>
                      {(r.applies_to_roles.length > 0 ||
                        r.sources.length > 0) && (
                        <div
                          style={{
                            marginTop: 6,
                            fontSize: 11,
                            fontFamily: "var(--wg-font-mono)",
                            color: "var(--wg-ink-faint)",
                            display: "flex",
                            gap: 12,
                            flexWrap: "wrap",
                          }}
                        >
                          {r.applies_to_roles.length > 0 && (
                            <span>
                              {t("rolesPrefix")}{" "}
                              {r.applies_to_roles.join(", ")}
                            </span>
                          )}
                          {r.sources.length > 0 && (
                            <span>
                              {t("sourcesPrefix")} {r.sources.join(", ")}
                            </span>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <em style={mutedText}>{t("noRoutines")}</em>
              )}
            </div>

            <div>
              <button
                type="button"
                onClick={() => setBriefOpen((v) => !v)}
                style={{
                  ...secondaryButton(),
                  padding: "4px 10px",
                  fontSize: 11,
                }}
              >
                {briefOpen ? t("hideBrief") : t("showBrief")}
              </button>
              {briefOpen && (
                <pre
                  style={{
                    marginTop: 8,
                    padding: 12,
                    background: "var(--wg-surface)",
                    border: "1px solid var(--wg-line-soft, var(--wg-line))",
                    borderRadius: 6,
                    fontSize: 12,
                    lineHeight: 1.55,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {draft.brief_markdown}
                </pre>
              )}
            </div>

            <div style={{ display: "flex", gap: 8 }}>
              {draft.status === "draft" ? (
                <button
                  type="button"
                  onClick={() => void handleFinalize()}
                  disabled={finalizing}
                  style={primaryButton(finalizing)}
                >
                  {finalizing ? t("finalizing") : t("finalizeButton")}
                </button>
              ) : (
                <span
                  style={{
                    alignSelf: "center",
                    color: "var(--wg-ok, #2f8f4f)",
                    fontSize: 12,
                    fontFamily: "var(--wg-font-mono)",
                    fontWeight: 600,
                  }}
                >
                  {t("finalized")}
                </span>
              )}
              <button
                type="button"
                onClick={onClose}
                style={secondaryButton()}
              >
                {t("close")}
              </button>
            </div>
          </section>
        )}

        {error && (
          <div
            role="alert"
            style={{
              padding: "8px 12px",
              background: "var(--wg-amber-soft)",
              border: "1px solid var(--wg-amber)",
              borderRadius: 6,
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink)",
            }}
          >
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusChip({
  status,
  labelDraft,
  labelFinalized,
}: {
  status: "draft" | "finalized";
  labelDraft: string;
  labelFinalized: string;
}) {
  const isFinal = status === "finalized";
  return (
    <span
      style={{
        padding: "2px 8px",
        background: isFinal
          ? "rgba(22, 163, 74,0.15)"
          : "var(--wg-amber-soft)",
        color: isFinal ? "var(--wg-ok, #2f8f4f)" : "var(--wg-amber)",
        border: `1px solid ${
          isFinal ? "var(--wg-ok, #2f8f4f)" : "var(--wg-amber)"
        }`,
        borderRadius: 12,
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
      }}
    >
      {isFinal ? labelFinalized : labelDraft}
    </span>
  );
}

function Chip({
  label,
  tone,
}: {
  label: string;
  tone: "role" | "routine";
}) {
  const s =
    tone === "role"
      ? {
          bg: "var(--wg-accent-soft)",
          fg: "var(--wg-accent)",
          border: "var(--wg-accent-ring, var(--wg-accent))",
        }
      : {
          bg: "var(--wg-surface)",
          fg: "var(--wg-ink)",
          border: "var(--wg-line)",
        };
  return (
    <span
      style={{
        padding: "3px 9px",
        background: s.bg,
        color: s.fg,
        border: `1px solid ${s.border}`,
        borderRadius: 12,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
      }}
    >
      {label}
    </span>
  );
}

const mutedText: CSSProperties = {
  fontSize: 12,
  color: "var(--wg-ink-faint)",
};

function primaryButton(busy: boolean): CSSProperties {
  return {
    padding: "7px 14px",
    background: "var(--wg-accent)",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 600,
    cursor: busy ? "progress" : "pointer",
    opacity: busy ? 0.6 : 1,
  };
}

function secondaryButton(): CSSProperties {
  return {
    padding: "7px 14px",
    background: "var(--wg-surface)",
    color: "var(--wg-ink)",
    border: "1px solid var(--wg-line)",
    borderRadius: 6,
    fontSize: 13,
    cursor: "pointer",
  };
}
