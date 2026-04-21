"use client";

// RouteProposalCard — Phase N.
//
// Renders the edge-agent's "route proposal" turn in the user's personal
// stream (north-star §"Sub-agent and routing architecture" → "Route
// proposal"). The body shows the agent's framing; 1–3 "Ask [name]"
// buttons fire the confirm endpoint which dispatches via the parent
// agent. A dismiss (×) control hides the card locally (backend decline
// endpoint TBD — see report).
//
// Targets are either pre-parsed on the message (`route_targets`) or
// extracted client-side from a `<route-proposal>{targets:[…]}</…>`
// marker in the body (see `parseRouteProposalTargets` in lib/api).

import { useMemo, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  confirmRouteProposal,
  fetchPreAnswer,
  parseRouteProposalFromBody,
  runScrimmage,
  stripRouteProposalMarker,
  type PersonalMessage,
  type PersonalRouteTarget,
  type PreAnswerPayload,
  type ScrimmageResult,
} from "@/lib/api";

import {
  DebateSummaryCard,
  DecisionProposalCard,
  ScrimmageRunningCard,
} from "./ScrimmageCards";
import { relativeTime } from "./types";

type Props = {
  message: PersonalMessage;
  // project_id is needed for the Stage 2 pre-answer endpoint, which is
  // scoped to /api/projects/{id}/pre-answer. The classic
  // `confirmRouteProposal` call doesn't need it, so it stays optional
  // for backwards compatibility — if omitted, the preview button is
  // hidden and only the classic "Ask X" flow remains.
  projectId?: string;
  // Parent may want to refresh its timeline after a dispatch so the new
  // "routed-reply" card can land. We fire-and-forget here; parent is
  // informed via the optional callback.
  onConfirmed?: (signalId: string) => void;
};

const primaryBtn: CSSProperties = {
  padding: "6px 12px",
  background: "var(--wg-accent)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

const dismissBtn: CSSProperties = {
  marginLeft: "auto",
  padding: "2px 8px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
};

const secondaryBtn: CSSProperties = {
  padding: "6px 10px",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  cursor: "pointer",
};

export function RouteProposalCard({
  message,
  projectId,
  onConfirmed,
}: Props) {
  const t = useTranslations("personal");

  // Prefer pre-parsed backend metadata; fall back to embedded marker if
  // the payload wasn't shaped (e.g. older API build).
  const proposal = useMemo(() => {
    if (message.route_proposal) return message.route_proposal;
    return parseRouteProposalFromBody(message.body);
  }, [message]);

  const targets = useMemo<PersonalRouteTarget[]>(
    () => proposal?.targets ?? [],
    [proposal],
  );

  // If the backend stripped the marker for us, use body as-is; otherwise
  // strip defensively. Prefer proposal.framing when present because that
  // is the canonical framing text the agent composed.
  const displayBody = useMemo(() => {
    if (proposal?.framing) return proposal.framing;
    return stripRouteProposalMarker(message.body);
  }, [message.body, proposal]);

  // Local state — backend decline endpoint not yet wired.
  const [dismissed, setDismissed] = useState(false);
  const [confirmedName, setConfirmedName] = useState<string | null>(null);
  const [pendingTargetId, setPendingTargetId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Scrimmage toggle + run state (PLAN-v3 §2.B). `scrimmageEnabled` is a
  // per-target checkbox — "Try scrimmage first". When set, "Ask X"
  // triggers POST /api/projects/{id}/scrimmages instead of the classic
  // route-proposal confirm endpoint. `scrimmageRunningFor` / `scrimmageResult`
  // drive the in-flight + result cards.
  const [scrimmageEnabled, setScrimmageEnabled] = useState<Record<string, boolean>>(
    {},
  );
  const [scrimmageRunningFor, setScrimmageRunningFor] = useState<string | null>(
    null,
  );
  const [scrimmageResult, setScrimmageResult] = useState<ScrimmageResult | null>(
    null,
  );
  const [scrimmageTargetName, setScrimmageTargetName] = useState<string>("");
  const [scrimmageError, setScrimmageError] = useState<string | null>(null);

  // Stage 2: pre-answer preview state. Keyed by target user id so each
  // "Preview X" button tracks its own fetch without clobbering siblings.
  const [previewingTargetId, setPreviewingTargetId] = useState<string | null>(
    null,
  );
  const [preAnswers, setPreAnswers] = useState<
    Record<string, PreAnswerPayload>
  >({});
  const [preAnswerError, setPreAnswerError] = useState<
    Record<string, string>
  >({});
  const [acceptedTargetId, setAcceptedTargetId] = useState<string | null>(null);

  if (dismissed) {
    return (
      <div
        data-testid="personal-route-proposal-dismissed"
        style={{
          marginBottom: 8,
          marginLeft: 42,
          padding: "4px 10px",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
        }}
      >
        {t("routeProposal.dismissed")}
      </div>
    );
  }

  async function handlePreview(target: PersonalRouteTarget) {
    if (!projectId) return;
    if (previewingTargetId) return;
    setPreviewingTargetId(target.user_id);
    setPreAnswerError((prev) => {
      const next = { ...prev };
      delete next[target.user_id];
      return next;
    });
    // Use the proposal framing as the question when available — it's
    // what the agent already framed; otherwise fall back to the raw
    // body. Either way the target's edge gets a concrete prompt.
    const question =
      (proposal?.framing && proposal.framing.trim()) ||
      (message.body || "").trim() ||
      target.rationale ||
      "(no framing)";
    try {
      const payload = await fetchPreAnswer(
        projectId,
        target.user_id,
        question,
      );
      setPreAnswers((prev) => ({ ...prev, [target.user_id]: payload }));
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? "")
            : `error ${e.status}`
          : "preview failed";
      setPreAnswerError((prev) => ({
        ...prev,
        [target.user_id]: msg || t("routeProposal.preAnswer.failed"),
      }));
    } finally {
      setPreviewingTargetId(null);
    }
  }

  function handleAccept(target: PersonalRouteTarget) {
    setAcceptedTargetId(target.user_id);
  }

  async function handleAsk(
    target: PersonalRouteTarget,
    options?: { forceClassic?: boolean },
  ) {
    if (pendingTargetId || scrimmageRunningFor) return;
    const forceClassic = options?.forceClassic === true;

    // Scrimmage branch — requires projectId so the /scrimmages route
    // builds; silently degrades to classic confirm if projectId is
    // absent (legacy callers).
    if (!forceClassic && scrimmageEnabled[target.user_id] && projectId) {
      setScrimmageRunningFor(target.user_id);
      setScrimmageResult(null);
      setScrimmageError(null);
      setScrimmageTargetName(target.display_name);
      const question =
        (proposal?.framing && proposal.framing.trim()) ||
        (message.body || "").trim() ||
        target.rationale ||
        "(no framing)";
      try {
        const res = await runScrimmage(projectId, target.user_id, question);
        setScrimmageResult(res);
      } catch (e) {
        if (e instanceof ApiError) {
          const detail =
            typeof e.body === "object" && e.body && "detail" in e.body
              ? String((e.body as { detail?: unknown }).detail ?? "")
              : `error ${e.status}`;
          setScrimmageError(detail || `error ${e.status}`);
        } else {
          setScrimmageError("scrimmage failed");
        }
      } finally {
        setScrimmageRunningFor(null);
      }
      return;
    }

    setPendingTargetId(target.user_id);
    setError(null);
    try {
      const result = await confirmRouteProposal(message.id, target.user_id);
      setConfirmedName(target.display_name);
      onConfirmed?.(result.signal_id);
    } catch (e) {
      setPendingTargetId(null);
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? "")
            : `error ${e.status}`;
        setError(detail || `error ${e.status}`);
      } else {
        setError("ask failed");
      }
    }
  }

  async function handleAskDirectlyAfterScrimmage() {
    // Unresolved path: user wants to route the original question
    // through the classic flow. We synthesize a target from the stored
    // scrimmage result + matching entry in `targets` so confirm lands.
    if (!scrimmageResult) return;
    const target = targets.find(
      (tg) => tg.user_id === scrimmageResult.target_user_id,
    );
    if (!target) return;
    // Force classic route even if toggle is still on — this is the
    // "fall back to direct routing" path.
    setScrimmageResult(null);
    setScrimmageError(null);
    await handleAsk(target, { forceClassic: true });
  }

  return (
    <div
      data-testid="personal-route-proposal"
      data-message-id={message.id}
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: "10px 14px",
        background: "var(--wg-accent-soft, #fdf4ec)",
        border: "1px solid var(--wg-accent-ring, var(--wg-accent))",
        borderLeft: "3px solid var(--wg-accent)",
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-accent)",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          fontWeight: 600,
          marginBottom: 6,
        }}
      >
        <span>{t("routeProposal.header")}</span>
        <span
          title={new Date(message.created_at).toLocaleString()}
          style={{ color: "var(--wg-ink-soft)", textTransform: "none", fontWeight: 400 }}
        >
          {relativeTime(message.created_at)}
        </span>
      </div>

      {displayBody && (
        <div
          style={{
            color: "var(--wg-ink)",
            marginBottom: 10,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {displayBody}
        </div>
      )}

      {acceptedTargetId && !confirmedName ? (
        <div
          data-testid="personal-route-proposal-preanswer-accepted"
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 12,
            color: "var(--wg-ok, #2f8f4f)",
            fontWeight: 600,
          }}
        >
          {t("routeProposal.preAnswer.accepted")}
        </div>
      ) : confirmedName ? (
        <div
          data-testid="personal-route-proposal-confirmed"
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 12,
            color: "var(--wg-ok, #2f8f4f)",
            fontWeight: 600,
          }}
        >
          {t("routeProposal.confirmed", { name: confirmedName })}
        </div>
      ) : (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            alignItems: "center",
          }}
        >
          {targets.length === 0 && (
            <span
              style={{
                fontSize: 12,
                color: "var(--wg-ink-soft)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t("routeProposal.noTargets")}
            </span>
          )}
          {targets.map((tg) => {
            const busy = pendingTargetId === tg.user_id;
            const previewing = previewingTargetId === tg.user_id;
            const draft = preAnswers[tg.user_id];
            const previewError = preAnswerError[tg.user_id];
            return (
              <div
                key={tg.user_id}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  minWidth: 0,
                  flex: "1 1 220px",
                }}
              >
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    disabled={pendingTargetId !== null}
                    onClick={() => void handleAsk(tg)}
                    data-testid="personal-route-ask-btn"
                    data-target-user-id={tg.user_id}
                    style={{
                      ...primaryBtn,
                      opacity: pendingTargetId && !busy ? 0.5 : 1,
                      cursor: pendingTargetId ? "progress" : "pointer",
                    }}
                    title={tg.rationale}
                  >
                    {busy
                      ? t("routeProposal.asking", { name: tg.display_name })
                      : t("routeProposal.ask", { name: tg.display_name })}
                  </button>
                  {projectId && !draft ? (
                    <button
                      type="button"
                      disabled={previewingTargetId !== null}
                      onClick={() => void handlePreview(tg)}
                      data-testid="personal-route-preview-btn"
                      data-target-user-id={tg.user_id}
                      style={{
                        ...secondaryBtn,
                        opacity:
                          previewingTargetId && !previewing ? 0.5 : 1,
                        cursor: previewingTargetId ? "progress" : "pointer",
                      }}
                    >
                      {previewing
                        ? t("routeProposal.preAnswer.previewing", {
                            name: tg.display_name,
                          })
                        : t("routeProposal.preAnswer.preview", {
                            name: tg.display_name,
                          })}
                    </button>
                  ) : null}
                </div>
                {projectId ? (
                  <label
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      fontSize: 11,
                      fontFamily: "var(--wg-font-mono)",
                      color: "var(--wg-ink-soft)",
                      cursor: "pointer",
                    }}
                    data-testid="scrimmage-toggle-label"
                    data-target-user-id={tg.user_id}
                  >
                    <input
                      type="checkbox"
                      checked={scrimmageEnabled[tg.user_id] === true}
                      onChange={(ev) =>
                        setScrimmageEnabled((prev) => ({
                          ...prev,
                          [tg.user_id]: ev.target.checked,
                        }))
                      }
                      data-testid="scrimmage-toggle"
                      data-target-user-id={tg.user_id}
                    />
                    <span>{t("routeProposal.scrimmage.toggle")}</span>
                  </label>
                ) : null}
                {previewError ? (
                  <span
                    role="alert"
                    style={{
                      fontSize: 11,
                      fontFamily: "var(--wg-font-mono)",
                      color: "var(--wg-accent)",
                    }}
                  >
                    {previewError}
                  </span>
                ) : null}
                {draft ? (
                  <PreAnswerPanel
                    target={tg}
                    payload={draft}
                    onAccept={() => handleAccept(tg)}
                    onRouteAnyway={() => void handleAsk(tg)}
                    busy={busy}
                    t={t}
                  />
                ) : null}
              </div>
            );
          })}
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label={t("routeProposal.dismiss")}
            title={t("routeProposal.dismiss")}
            data-testid="personal-route-dismiss-btn"
            style={dismissBtn}
          >
            ×
          </button>
        </div>
      )}

      {scrimmageRunningFor && projectId ? (
        <ScrimmageRunningCard
          sourceName={t("routeProposal.scrimmage.youLabel")}
          targetName={scrimmageTargetName}
        />
      ) : null}

      {scrimmageResult && projectId ? (
        scrimmageResult.outcome === "converged_proposal" ? (
          <DecisionProposalCard
            projectId={projectId}
            result={scrimmageResult}
            sourceName={t("routeProposal.scrimmage.youLabel")}
            targetName={scrimmageTargetName}
            onReject={() => {
              setScrimmageResult(null);
            }}
          />
        ) : scrimmageResult.outcome === "unresolved_crux" ? (
          <DebateSummaryCard
            projectId={projectId}
            result={scrimmageResult}
            sourceName={t("routeProposal.scrimmage.youLabel")}
            targetName={scrimmageTargetName}
            onAskDirectly={() => void handleAskDirectlyAfterScrimmage()}
          />
        ) : null
      ) : null}

      {scrimmageError ? (
        <div
          role="alert"
          style={{
            marginTop: 6,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {scrimmageError}
        </div>
      ) : null}

      {error && (
        <div
          role="alert"
          style={{
            marginTop: 6,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {error}
        </div>
      )}
      <style>{`
        @keyframes wgSpin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

function PreAnswerPanel({
  target,
  payload,
  onAccept,
  onRouteAnyway,
  busy,
  t,
}: {
  target: PersonalRouteTarget;
  payload: PreAnswerPayload;
  onAccept: () => void;
  onRouteAnyway: () => void;
  busy: boolean;
  t: (
    key: string,
    values?: Record<string, string | number>,
  ) => string;
}) {
  const draft = payload.draft;
  const confColor =
    draft.confidence === "high"
      ? "var(--wg-ok, #2f8f4f)"
      : draft.confidence === "medium"
        ? "var(--wg-accent)"
        : "var(--wg-ink-soft)";
  const confLabel =
    draft.confidence === "high"
      ? t("routeProposal.preAnswer.confidenceHigh")
      : draft.confidence === "medium"
        ? t("routeProposal.preAnswer.confidenceMedium")
        : t("routeProposal.preAnswer.confidenceLow");
  return (
    <div
      data-testid="personal-pre-answer-panel"
      data-target-user-id={target.user_id}
      style={{
        marginTop: 4,
        padding: "10px 12px",
        background: "var(--wg-surface)",
        border: "1px solid var(--wg-line)",
        borderLeft: `3px solid ${confColor}`,
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 12,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--wg-ink-faint)",
          display: "flex",
          justifyContent: "space-between",
          gap: 10,
        }}
      >
        <span>
          {t("routeProposal.preAnswer.header", { name: target.display_name })}
        </span>
        <span style={{ color: confColor, fontWeight: 600 }}>{confLabel}</span>
      </div>
      <div
        style={{
          fontSize: 11,
          fontStyle: "italic",
          color: "var(--wg-ink-faint)",
          marginTop: -2,
        }}
      >
        {t("routeProposal.preAnswer.subheader", { name: target.display_name })}
      </div>
      <div
        style={{
          color: "var(--wg-ink)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          lineHeight: 1.5,
        }}
      >
        {draft.body}
      </div>
      {draft.matched_skills.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
              textTransform: "uppercase",
            }}
          >
            {t("routeProposal.preAnswer.matchedLabel")}
          </span>
          {draft.matched_skills.map((s) => (
            <SkillChip key={s} label={s} tone="matched" />
          ))}
        </div>
      ) : null}
      {draft.uncovered_topics.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
              textTransform: "uppercase",
            }}
          >
            {t("routeProposal.preAnswer.uncoveredLabel")}
          </span>
          {draft.uncovered_topics.map((s) => (
            <SkillChip key={s} label={s} tone="uncovered" />
          ))}
        </div>
      ) : null}
      {draft.rationale ? (
        <div
          style={{
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            paddingTop: 4,
            borderTop: "1px dashed var(--wg-line-soft, var(--wg-line))",
          }}
        >
          <span
            style={{
              fontFamily: "var(--wg-font-mono)",
              textTransform: "uppercase",
              fontSize: 10,
              color: "var(--wg-ink-faint)",
              marginRight: 6,
            }}
          >
            {t("routeProposal.preAnswer.rationaleLabel")}
          </span>
          {draft.rationale}
        </div>
      ) : null}
      <div
        style={{
          display: "flex",
          gap: 8,
          paddingTop: 4,
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          onClick={onAccept}
          data-testid="personal-pre-answer-accept-btn"
          style={{
            padding: "5px 10px",
            background: "var(--wg-ok, #2f8f4f)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius)",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {t("routeProposal.preAnswer.accept")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onRouteAnyway}
          data-testid="personal-pre-answer-route-btn"
          style={{
            padding: "5px 10px",
            background: "var(--wg-surface)",
            color: "var(--wg-accent)",
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius)",
            fontSize: 12,
            fontWeight: 600,
            cursor: busy ? "progress" : "pointer",
            opacity: busy ? 0.6 : 1,
          }}
        >
          {t("routeProposal.preAnswer.routeAnyway", {
            name: target.display_name,
          })}
        </button>
      </div>
    </div>
  );
}

function SkillChip({
  label,
  tone,
}: {
  label: string;
  tone: "matched" | "uncovered";
}) {
  const s =
    tone === "matched"
      ? {
          bg: "rgba(77,122,74,0.12)",
          fg: "var(--wg-ok, #2f8f4f)",
          border: "var(--wg-ok, #2f8f4f)",
        }
      : {
          bg: "var(--wg-amber-soft)",
          fg: "var(--wg-amber)",
          border: "var(--wg-amber)",
        };
  return (
    <span
      style={{
        padding: "2px 7px",
        background: s.bg,
        color: s.fg,
        border: `1px solid ${s.border}`,
        borderRadius: 10,
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
      }}
    >
      {label}
    </span>
  );
}
