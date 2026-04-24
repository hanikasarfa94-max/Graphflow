"use client";

// GatedInboxItem — Phase S sidebar-inbox card for the two halves of
// gated-proposal workload:
//
//   * kind='gate-sign-off' — caller is the named gate-keeper. Shows
//     approve/deny buttons + rationale textarea (same shape as the
//     personal-stream GatedProposalPendingCard, but compact for the
//     drawer list).
//   * kind='vote-pending'  — caller is in voter_pool. Shows the live
//     tally (approve/deny/abstain counts, threshold), three verdict
//     buttons, rationale textarea. `my_vote` (if non-null) highlights
//     the user's current verdict + lets them flip.
//
// Resolution collapses the card to a terminal state so the drawer
// clearly shows what just happened without yanking the row from the
// list mid-interaction.

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  approveGatedProposal,
  castGatedProposalVote,
  denyGatedProposal,
  getGatedProposalCounterfactual,
  getGatedProposalTally,
  type Counterfactual,
  type GatedInboxItem as GatedInboxItemType,
  type TallySnapshot,
  type VoteVerdict,
} from "@/lib/api";

const CLASS_LABELS: Record<string, { en: string; zh: string }> = {
  budget: { en: "Budget", zh: "预算" },
  legal: { en: "Legal", zh: "法务" },
  hire: { en: "Hire", zh: "招聘" },
  scope_cut: { en: "Scope", zh: "范围" },
};

export function GatedInboxItem({
  item,
  onResolved,
}: {
  item: GatedInboxItemType;
  onResolved: (proposalId: string) => void;
}) {
  if (item.kind === "gate-sign-off") {
    return <SignOffItem item={item} onResolved={onResolved} />;
  }
  return <VoteItem item={item} onResolved={onResolved} />;
}

function DecisionClassChip({ cls }: { cls: string }) {
  const label = CLASS_LABELS[cls]?.en ?? cls;
  return (
    <span
      data-decision-class={cls}
      style={{
        padding: "1px 6px",
        background: "var(--wg-amber-soft)",
        color: "var(--wg-amber)",
        border: "1px solid var(--wg-amber)",
        borderRadius: "var(--wg-radius-sm, 4px)",
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  );
}

// ---- gate-sign-off (single-approver) -----------------------------------

function SignOffItem({
  item,
  onResolved,
}: {
  item: GatedInboxItemType;
  onResolved: (proposalId: string) => void;
}) {
  const t = useTranslations("personal.gatedProposal");
  const [actioning, setActioning] = useState<"approve" | "deny" | null>(null);
  const [resolvedAs, setResolvedAs] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  async function handleApprove() {
    if (actioning) return;
    setActioning("approve");
    setError(null);
    try {
      await approveGatedProposal(item.proposal.id, note.trim() || undefined);
      setResolvedAs("approved");
      onResolved(item.proposal.id);
    } catch (e) {
      setError(extractError(e, "approve failed"));
    } finally {
      setActioning(null);
    }
  }

  async function handleDeny() {
    if (actioning) return;
    setActioning("deny");
    setError(null);
    try {
      await denyGatedProposal(item.proposal.id, note.trim() || undefined);
      setResolvedAs("denied");
      onResolved(item.proposal.id);
    } catch (e) {
      setError(extractError(e, "deny failed"));
    } finally {
      setActioning(null);
    }
  }

  return (
    <div
      data-testid="gated-inbox-sign-off"
      data-proposal-id={item.proposal.id}
      style={{
        padding: "12px 14px",
        background: "var(--wg-surface-sunk, var(--wg-surface))",
        borderLeft: "3px solid var(--wg-amber)",
        borderRadius: "var(--wg-radius-sm, 4px)",
      }}
    >
      <Header
        icon="⚖"
        label={t("header")}
        cls={item.proposal.decision_class}
        createdAt={item.created_at}
      />
      {item.proposal.decision_text &&
      item.proposal.decision_text.trim() !==
        (item.proposal.proposal_body || "").trim() ? (
        <RawUtteranceBlock text={item.proposal.decision_text} />
      ) : null}
      <div
        style={{
          color: "var(--wg-ink)",
          marginBottom: 10,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontSize: 13,
          lineHeight: 1.5,
        }}
      >
        {item.proposal.proposal_body}
      </div>
      {resolvedAs ? (
        <ResolvedBadge status={resolvedAs} />
      ) : (
        <>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("resolutionNotePlaceholder")}
            rows={2}
            maxLength={2000}
            style={textareaStyle}
          />
          <div style={buttonRow}>
            <button
              type="button"
              disabled={actioning !== null}
              onClick={() => void handleApprove()}
              data-testid="gated-inbox-approve-btn"
              style={primaryBtn("ok", actioning === "approve")}
            >
              {actioning === "approve" ? t("approving") : t("approve")}
            </button>
            <button
              type="button"
              disabled={actioning !== null}
              onClick={() => void handleDeny()}
              data-testid="gated-inbox-deny-btn"
              style={secondaryBtn(actioning === "deny")}
            >
              {actioning === "deny" ? t("denying") : t("deny")}
            </button>
          </div>
        </>
      )}
      {error ? <ErrorLine text={error} /> : null}
    </div>
  );
}

// ---- vote-pending ------------------------------------------------------

function VoteItem({
  item,
  onResolved,
}: {
  item: GatedInboxItemType;
  onResolved: (proposalId: string) => void;
}) {
  const t = useTranslations("personal.gatedProposal");
  const tv = useTranslations("vote");
  const [tally, setTally] = useState<TallySnapshot | null>(null);
  const [actioning, setActioning] = useState<VoteVerdict | null>(null);
  const [myVerdict, setMyVerdict] = useState<VoteVerdict | null>(
    item.my_vote?.verdict ?? null,
  );
  const [resolvedAs, setResolvedAs] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rationale, setRationale] = useState(item.my_vote?.rationale ?? "");
  // Counterfactual preview — the "if approved" block between the tally
  // row and the rationale textarea. Loading / error are local so a
  // counterfactual fetch failure never blocks voting.
  const [cf, setCf] = useState<Counterfactual | null>(null);
  const [cfLoading, setCfLoading] = useState(true);
  const [cfFailed, setCfFailed] = useState(false);

  // Refresh tally on mount so the drawer shows live counts if someone
  // else voted between preload and drawer open.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const snap = await getGatedProposalTally(item.proposal.id);
        if (!cancelled) setTally(snap);
      } catch {
        /* non-fatal */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.proposal.id]);

  // Fetch counterfactual on mount. Independent from tally so a slow
  // simulate call doesn't delay showing live counts.
  useEffect(() => {
    let cancelled = false;
    setCfLoading(true);
    setCfFailed(false);
    (async () => {
      try {
        const res = await getGatedProposalCounterfactual(item.proposal.id);
        if (!cancelled) {
          setCf(res);
          setCfLoading(false);
        }
      } catch {
        if (!cancelled) {
          setCfFailed(true);
          setCfLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [item.proposal.id]);

  async function handleCast(verdict: VoteVerdict) {
    if (actioning) return;
    setActioning(verdict);
    setError(null);
    try {
      const res = await castGatedProposalVote(item.proposal.id, {
        verdict,
        rationale: rationale.trim() || undefined,
      });
      setMyVerdict(verdict);
      setTally({
        approve: res.tally.approve,
        deny: res.tally.deny,
        abstain: res.tally.abstain,
        outstanding: res.tally.outstanding,
        pool_size: res.tally.pool_size,
        threshold: res.tally.threshold,
        votes: tally?.votes ?? [],
      });
      if (res.resolved_as) {
        setResolvedAs(res.resolved_as);
        onResolved(item.proposal.id);
      }
    } catch (e) {
      setError(extractError(e, "vote failed"));
    } finally {
      setActioning(null);
    }
  }

  const pool = item.proposal.voter_pool ?? [];
  const threshold = tally?.threshold ?? (pool.length > 0 ? Math.floor(pool.length / 2) + 1 : null);
  const approve = tally?.approve ?? 0;
  const deny = tally?.deny ?? 0;
  const abstain = tally?.abstain ?? 0;
  const poolSize = tally?.pool_size ?? pool.length;

  const tallyRow = useMemo(
    () => (
      <div
        data-testid="gated-inbox-tally"
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <span style={{ color: "var(--wg-ok)", fontWeight: 600 }}>
          ✓ {approve}
        </span>
        <span style={{ color: "var(--wg-accent)", fontWeight: 600 }}>
          ✗ {deny}
        </span>
        {abstain > 0 ? <span>~ {abstain}</span> : null}
        <span style={{ marginLeft: "auto" }}>
          {tv("thresholdLabel", {
            threshold: threshold ?? 0,
            pool: poolSize,
          })}
        </span>
      </div>
    ),
    [approve, deny, abstain, poolSize, threshold, tv],
  );

  return (
    <div
      data-testid="gated-inbox-vote"
      data-proposal-id={item.proposal.id}
      style={{
        padding: "12px 14px",
        background: "var(--wg-surface-sunk, var(--wg-surface))",
        borderLeft: "3px solid var(--wg-amber)",
        borderRadius: "var(--wg-radius-sm, 4px)",
      }}
    >
      <Header
        icon="🗳"
        label={tv("pendingLabel")}
        cls={item.proposal.decision_class}
        createdAt={item.created_at}
      />
      {item.proposal.decision_text &&
      item.proposal.decision_text.trim() !==
        (item.proposal.proposal_body || "").trim() ? (
        <RawUtteranceBlock text={item.proposal.decision_text} />
      ) : null}
      <div
        style={{
          color: "var(--wg-ink)",
          marginBottom: 10,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontSize: 13,
          lineHeight: 1.5,
        }}
      >
        {item.proposal.proposal_body}
      </div>
      {tallyRow}
      <CounterfactualBlock cf={cf} loading={cfLoading} failed={cfFailed} />
      {resolvedAs ? (
        <ResolvedBadge status={resolvedAs} />
      ) : (
        <>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder={tv("rationalePlaceholder")}
            rows={2}
            maxLength={2000}
            style={textareaStyle}
          />
          <div style={buttonRow}>
            <VerdictBtn
              verdict="approve"
              my={myVerdict}
              actioning={actioning}
              onClick={() => void handleCast("approve")}
              label={tv(myVerdict === "approve" ? "yourApprove" : "approve")}
              testid="gated-inbox-vote-approve-btn"
            />
            <VerdictBtn
              verdict="deny"
              my={myVerdict}
              actioning={actioning}
              onClick={() => void handleCast("deny")}
              label={tv(myVerdict === "deny" ? "yourDeny" : "deny")}
              testid="gated-inbox-vote-deny-btn"
            />
            <VerdictBtn
              verdict="abstain"
              my={myVerdict}
              actioning={actioning}
              onClick={() => void handleCast("abstain")}
              label={tv(myVerdict === "abstain" ? "yourAbstain" : "abstain")}
              testid="gated-inbox-vote-abstain-btn"
            />
          </div>
        </>
      )}
      {error ? <ErrorLine text={error} /> : null}
    </div>
  );
}

// ---- shared bits -------------------------------------------------------

function Header({
  icon,
  label,
  cls,
  createdAt,
}: {
  icon: string;
  label: string;
  cls: string;
  createdAt: string | null;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        color: "var(--wg-amber)",
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        fontWeight: 600,
        marginBottom: 8,
        gap: 8,
      }}
    >
      <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span aria-hidden="true">{icon}</span>
        <span>{label}</span>
        <DecisionClassChip cls={cls} />
      </span>
      {createdAt ? (
        <span
          title={new Date(createdAt).toLocaleString()}
          style={{
            color: "var(--wg-ink-soft)",
            textTransform: "none",
            fontWeight: 400,
          }}
        >
          {relativeShort(createdAt)}
        </span>
      ) : null}
    </div>
  );
}

function RawUtteranceBlock({ text }: { text: string }) {
  const t = useTranslations("personal.gatedProposal");
  return (
    <div
      data-testid="gated-inbox-raw"
      style={{
        marginBottom: 10,
        padding: "8px 10px",
        background: "var(--wg-surface-raised, var(--wg-surface))",
        borderLeft: "2px solid var(--wg-ink-faint)",
        borderRadius: "var(--wg-radius-sm, 4px)",
      }}
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 10,
          color: "var(--wg-ink-faint)",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          fontWeight: 600,
          marginBottom: 4,
        }}
      >
        {t("rawUtteranceLabel")}
      </div>
      <div
        style={{
          color: "var(--wg-ink)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          lineHeight: 1.5,
          fontSize: 13,
        }}
      >
        {text}
      </div>
    </div>
  );
}

function ResolvedBadge({ status }: { status: string }) {
  const t = useTranslations("personal.gatedProposal");
  return (
    <div
      data-testid="gated-inbox-resolved"
      style={{
        fontFamily: "var(--wg-font-mono)",
        fontSize: 12,
        fontWeight: 600,
        color:
          status === "approved" ? "var(--wg-ok)" : "var(--wg-ink-soft)",
      }}
    >
      {status === "approved" ? t("approved") : t("denied")}
    </div>
  );
}

function VerdictBtn({
  verdict,
  my,
  actioning,
  onClick,
  label,
  testid,
}: {
  verdict: VoteVerdict;
  my: VoteVerdict | null;
  actioning: VoteVerdict | null;
  onClick: () => void;
  label: string;
  testid: string;
}) {
  const isMine = my === verdict;
  const isBusy = actioning === verdict;
  const isOther = actioning !== null && actioning !== verdict;
  const palette =
    verdict === "approve"
      ? { solid: "var(--wg-ok)", line: "var(--wg-ok)" }
      : verdict === "deny"
        ? { solid: "var(--wg-accent)", line: "var(--wg-accent)" }
        : { solid: "var(--wg-ink-soft)", line: "var(--wg-line)" };
  return (
    <button
      type="button"
      disabled={actioning !== null}
      onClick={onClick}
      data-testid={testid}
      data-my={isMine ? "true" : "false"}
      style={{
        padding: "6px 12px",
        background: isMine ? palette.solid : "transparent",
        color: isMine ? "#fff" : palette.solid,
        border: `1px solid ${palette.line}`,
        borderRadius: "var(--wg-radius)",
        fontSize: 12,
        fontWeight: 600,
        cursor: actioning ? "progress" : "pointer",
        opacity: isOther ? 0.4 : 1,
      }}
    >
      {isBusy ? "…" : label}
    </button>
  );
}

// ---- counterfactual ("if approved") ------------------------------------
//
// Reads the GET /api/gated-proposals/{id}/counterfactual payload and
// renders a compact "if this passes, here's what changes" block. Three
// states: loading (shimmer line), error (silent-but-visible), payload.
// For v0 the most common payload is `empty: true, reason: 'no_actions'
// | 'advisory_only'` — we render one muted line for those, not an empty
// bullet list.
function CounterfactualBlock({
  cf,
  loading,
  failed,
}: {
  cf: Counterfactual | null;
  loading: boolean;
  failed: boolean;
}) {
  const t = useTranslations("vote");

  const containerStyle: React.CSSProperties = {
    marginBottom: 10,
    padding: "6px 10px",
    background: "var(--wg-surface-raised, var(--wg-surface))",
    borderLeft: "2px solid var(--wg-ink-faint)",
    borderRadius: "var(--wg-radius-sm, 4px)",
    fontSize: 11,
    lineHeight: 1.5,
  };
  const eyebrowStyle: React.CSSProperties = {
    fontFamily: "var(--wg-font-mono)",
    fontSize: 10,
    color: "var(--wg-ink-faint)",
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    fontWeight: 600,
    marginBottom: 2,
  };
  const mutedLine: React.CSSProperties = {
    color: "var(--wg-ink-soft)",
    fontStyle: "italic",
  };
  const bulletRow: React.CSSProperties = {
    display: "flex",
    gap: 6,
    alignItems: "baseline",
    color: "var(--wg-ink)",
    wordBreak: "break-word",
  };

  if (loading) {
    return (
      <div data-testid="gated-inbox-counterfactual" style={containerStyle}>
        <div style={eyebrowStyle}>{t("counterfactualEyebrow")}</div>
        <div style={mutedLine}>{t("counterfactualLoading")}</div>
      </div>
    );
  }

  if (failed || !cf) {
    // Silent-fail: show a tiny line but don't scream. Voting still
    // works regardless.
    return (
      <div data-testid="gated-inbox-counterfactual" style={containerStyle}>
        <div style={eyebrowStyle}>{t("counterfactualEyebrow")}</div>
        <div style={mutedLine}>{t("counterfactualError")}</div>
      </div>
    );
  }

  const hasEffects =
    cf.reassignments.length > 0 ||
    cf.unblocks.length > 0 ||
    cf.blocks.length > 0 ||
    cf.milestone_slips.length > 0;

  if (!hasEffects) {
    return (
      <div data-testid="gated-inbox-counterfactual" style={containerStyle}>
        <div style={eyebrowStyle}>{t("counterfactualEyebrow")}</div>
        <div style={mutedLine}>{t("counterfactualEmpty")}</div>
      </div>
    );
  }

  return (
    <div data-testid="gated-inbox-counterfactual" style={containerStyle}>
      <div style={eyebrowStyle}>{t("counterfactualEyebrow")}</div>
      {cf.unblocks.length > 0 ? (
        <div style={bulletRow} data-testid="cf-unblocks">
          <span style={{ color: "var(--wg-ok)", fontWeight: 600 }}>✓</span>
          <span>{t("counterfactualUnblocks", { n: cf.unblocks.length })}</span>
        </div>
      ) : null}
      {cf.blocks.length > 0 ? (
        <div style={bulletRow} data-testid="cf-blocks">
          <span style={{ color: "var(--wg-accent)", fontWeight: 600 }}>✗</span>
          <span>{t("counterfactualBlocks", { n: cf.blocks.length })}</span>
        </div>
      ) : null}
      {cf.milestone_slips.map((slip) => (
        <div style={bulletRow} key={slip.id} data-testid="cf-milestone-slip">
          <span style={{ color: "var(--wg-amber)", fontWeight: 600 }}>⚠</span>
          <span>
            {t("counterfactualMilestone", {
              days: slip.slip_days,
              name: slip.title,
            })}
          </span>
        </div>
      ))}
      {cf.reassignments.map((rx) => {
        const to = rx.to_display_name ?? "—";
        const from = rx.from_display_name;
        const title = rx.task_title || rx.task_id;
        const line = from
          ? t("counterfactualReassignFrom", { title, from, to })
          : t("counterfactualReassign", { title, to });
        return (
          <div style={bulletRow} key={rx.task_id} data-testid="cf-reassign">
            <span style={{ color: "var(--wg-accent)", fontWeight: 600 }}>→</span>
            <span>{line}</span>
          </div>
        );
      })}
    </div>
  );
}

function ErrorLine({ text }: { text: string }) {
  return (
    <div
      role="alert"
      style={{
        marginTop: 6,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        color: "var(--wg-accent)",
      }}
    >
      {text}
    </div>
  );
}

const textareaStyle = {
  width: "100%",
  padding: "6px 8px",
  background: "var(--wg-surface-raised, var(--wg-surface))",
  color: "var(--wg-ink)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 12,
  fontFamily: "var(--wg-font-body, inherit)",
  resize: "vertical" as const,
  boxSizing: "border-box" as const,
  marginBottom: 8,
};

const buttonRow = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap" as const,
};

function primaryBtn(
  color: "ok" | "accent",
  busy: boolean,
): React.CSSProperties {
  const solid = color === "ok" ? "var(--wg-ok)" : "var(--wg-accent)";
  return {
    padding: "6px 14px",
    background: solid,
    color: "#fff",
    border: "none",
    borderRadius: "var(--wg-radius)",
    fontSize: 12,
    fontWeight: 600,
    cursor: busy ? "progress" : "pointer",
    opacity: busy ? 0.6 : 1,
  };
}

function secondaryBtn(busy: boolean): React.CSSProperties {
  return {
    padding: "6px 14px",
    background: "transparent",
    color: "var(--wg-ink)",
    border: "1px solid var(--wg-line)",
    borderRadius: "var(--wg-radius)",
    fontSize: 12,
    fontWeight: 600,
    cursor: busy ? "progress" : "pointer",
    opacity: busy ? 0.6 : 1,
  };
}

function extractError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const body = e.body as { message?: unknown; detail?: unknown } | undefined;
    return (
      (body && typeof body.message === "string" && body.message) ||
      (body && typeof body.detail === "string" && body.detail) ||
      `error ${e.status}`
    );
  }
  return fallback;
}

function relativeShort(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}
