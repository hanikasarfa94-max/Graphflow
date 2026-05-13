"use client";

// MemoryReviewDrawer — the full Membrane review surface. The hardest
// doctrine UI in the product.
//
// Phase RW-3 (2026-05-13): four real mutation actions wired
// end-to-end. Accept / defer / reject / reopen POST to the live
// /api/memory-candidates/:id/{accept,defer,reject,reopen} endpoints
// and the drawer refetches the candidate (server-authoritative
// status) plus refreshes the parent Flow Center page so the table
// reflects the new state. No optimistic UI — the post-action render
// always comes from a fresh server payload.
//
// Phase RW-3.5 safety polish (2026-05-13): Revise is gone. The
// backend's accept_candidate doesn't take a revision body yet, so
// any FE-side edit to the proposed atom would be silently dropped
// (lineage.reviewer_revision_id stays null on the server). Leaving
// the Revise button + textarea visible was misleading; the button,
// the textarea, and the local revisedAtom buffer are removed. The
// proposed atom renders read-only verbatim from the server. Skip is
// a flow_response-side action and lives on MemoryPromptDrawer.
//
// Authority is server-driven. We render `authority.allowed_actions`
// as the source of truth for which buttons are enabled. No
// client-side role inference anywhere.
//
// DESIGN_LOCK.md invariants:
//   #6  Flow acceptance does not auto-accept memory.
//   #7  Memory crystallization is a separate decision.
//   #8  Memory acceptance requires server-side authority.
//   #9  Memory candidates must preserve lineage.

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button, Card, EmptyState, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";
import { ApiError, api } from "@/lib/api";

import { AuthorityState } from "./AuthorityState";
import {
  postCandidateAction,
  type ActionResult,
  type CandidateAction,
} from "./memoryCandidateActions";
import type { AllowedAction, MemoryCandidate } from "./types";

type FetchState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; candidate: MemoryCandidate };

function useFetchCandidate(id: string): {
  state: FetchState;
  refetch: () => void;
} {
  const [state, setState] = useState<FetchState>({ status: "loading" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    api<MemoryCandidate>(`/api/memory-candidates/${encodeURIComponent(id)}`)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", candidate: data });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? `Couldn't load memory candidate (${err.status})`
            : "Couldn't load memory candidate";
        setState({ status: "error", message: msg });
      });
    return () => {
      cancelled = true;
    };
  }, [id, tick]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);
  return { state, refetch };
}

// `postCandidateAction` lives in ./memoryCandidateActions so the
// bun:test decoder exercises don't transitively load the drawer
// chrome (lucide-react, Next.js client primitives). Re-exported at
// the bottom of this file for any caller that imported from here.

export function MemoryReviewDrawer({ candidate_id }: { candidate_id: string }) {
  const drawer = useDrawer();
  const { state, refetch } = useFetchCandidate(candidate_id);

  if (state.status === "loading") {
    return (
      <div style={{ padding: 24 }}>
        <Text variant="caption" muted>
          Loading memory candidate…
        </Text>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div style={{ padding: 24 }}>
        <EmptyState>{state.message}</EmptyState>
      </div>
    );
  }

  return (
    <MemoryReviewBody
      candidate={state.candidate}
      candidate_id={candidate_id}
      refetch={refetch}
      onClose={drawer.close}
    />
  );
}

function MemoryReviewBody({
  candidate,
  candidate_id,
  refetch,
  onClose,
}: {
  candidate: MemoryCandidate;
  candidate_id: string;
  refetch: () => void;
  onClose: () => void;
}) {
  const t = useTranslations("shellV062.flowCenter.memory");
  const router = useRouter();
  // RW-3.5 safety: the Revise button, textarea, and local
  // revisedAtom buffer are all removed. See file header for rationale.
  // The proposed atom renders read-only from candidate.proposed_memory_atom.
  const [pending, setPending] = useState<CandidateAction | null>(null);
  const [acceptedAnim, setAcceptedAnim] = useState(false);
  const [feedback, setFeedback] = useState<
    | { kind: "success"; message: string }
    | { kind: "error"; message: string }
    | null
  >(null);

  const authority = candidate.authority_check;
  const allowed = new Set<AllowedAction>(authority.allowed_actions);

  // First lifecycle event ≈ verbatim capture. Used to surface a
  // timestamp on the verbatim block since the wire shape no longer
  // carries an inline timestamp.
  const verbatimAt = candidate.lifecycle_events[0]?.at ?? null;

  function actionEnabled(a: CandidateAction): boolean {
    if (pending !== null) return false;
    return allowed.has(a);
  }

  async function runAction(action: CandidateAction) {
    if (!actionEnabled(action)) return;
    setPending(action);
    setFeedback(null);
    if (action === "accept") setAcceptedAnim(true);
    const result = await postCandidateAction(action, candidate_id);
    if (!result.ok) {
      setAcceptedAnim(false);
      setPending(null);
      const errKey = result.error ?? "unknown";
      const message =
        errKey === "authority_required"
          ? t("errors.authorityRequired", {
              role: result.required_role ?? "reviewer",
            })
          : errKey === "already_resolved"
            ? t("errors.alreadyResolved")
            : errKey === "not_reopenable"
              ? t("errors.notReopenable")
              : errKey === "not_found"
                ? t("errors.notFound")
                : errKey === "not_a_member"
                  ? t("errors.notMember")
                  : errKey === "network"
                    ? t("errors.network")
                    : t("errors.network");
      setFeedback({ kind: "error", message });
      return;
    }
    // Success — server is the source of truth for new status.
    // Refetch the candidate and refresh the parent server-component
    // so /flow-center's packet list reflects the transition.
    setFeedback({
      kind: "success",
      message: t(`success.${action === "accept" ? "accepted" : action === "defer" ? "deferred" : action === "reject" ? "rejected" : "reopened"}` as const),
    });
    // Accept brief beat for the motion moment, then close.
    if (action === "accept") {
      await new Promise((r) => setTimeout(r, 260));
      router.refresh();
      onClose();
      return;
    }
    // Non-accept actions: refetch + refresh parent so the user sees
    // the new authoritative state inside the drawer.
    refetch();
    router.refresh();
    setPending(null);
  }

  const acceptBlockedReason = authority.can_accept
    ? null
    : `Request review from a ${authority.required_roles[0] ?? "reviewer"}.`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Tag tone={candidate.status === "accepted" ? "ok" : "neutral"}>
        status: {candidate.status}
      </Tag>

      {/* 1. Verbatim source */}
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Text variant="caption" muted>
          Verbatim source
        </Text>
        <Card variant="sunk">
          <Text variant="caption" muted>
            {candidate.verbatim_source.author_user_id
              ? `user:${candidate.verbatim_source.author_user_id.slice(0, 8)}`
              : "anonymous"}
            {verbatimAt ? ` · ${verbatimAt}` : ""}
            {" · "}
            {candidate.verbatim_source.kind}
          </Text>
          <Text
            as="p"
            variant="mono"
            style={{ marginTop: 6, whiteSpace: "pre-wrap" }}
          >
            {candidate.verbatim_source.text || "(empty)"}
          </Text>
        </Card>
      </section>

      {/* 2. AI extracted claim */}
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Text variant="caption" muted>
          AI extracted claim
        </Text>
        <Text
          as="p"
          variant="body"
          style={{ fontStyle: "italic", color: "var(--wg-ink-soft)" }}
        >
          {candidate.ai_extracted_claim || "(no extracted claim)"}
        </Text>
      </section>

      {/* 3. Compression analysis — caveat string renders verbatim */}
      <section>
        <Card accent="amber">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Text variant="caption" muted>
                Compression analysis
              </Text>
              <Tag tone="amber">
                {candidate.compression_analysis.warning_count} warning
                {candidate.compression_analysis.warning_count === 1 ? "" : "s"}
              </Tag>
            </div>
            <Text variant="caption" muted>
              Method: {candidate.compression_analysis.method.join(" + ")}
            </Text>
            <Text as="p" variant="body">
              {/* Doctrine string — must render verbatim. */}
              {candidate.compression_analysis.caveat}
            </Text>
            {candidate.compression_warnings.length > 0 ? (
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {candidate.compression_warnings.map((w, i) => (
                  <li key={i}>
                    <Text variant="caption" muted>
                      {w}
                    </Text>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </Card>
      </section>

      {/* 4. Proposed memory atom — read-only.
            RW-3.5 safety: the Revise affordance was removed until
            the backend's accept_candidate takes a revision body.
            Today the AI's distillation is what gets accepted; any
            FE-side edit would be silently discarded. */}
      <section
        data-testid="memory-review-proposed-atom"
        style={{ display: "flex", flexDirection: "column", gap: 6 }}
      >
        <Text variant="caption" muted>
          Proposed memory atom · {candidate.proposed_memory_atom.tier}
        </Text>
        <Card accent="accent">
          <div className={acceptedAnim ? "wg-motion-memory-accept" : undefined}>
            {candidate.proposed_memory_atom.title ? (
              <Text
                as="p"
                variant="body"
                style={{ fontWeight: 600, marginBottom: 6 }}
              >
                {candidate.proposed_memory_atom.title}
              </Text>
            ) : null}
            <Text as="p" variant="body">
              {candidate.proposed_memory_atom.claim || "(no claim)"}
            </Text>
          </div>
        </Card>
      </section>

      {/* 5. Authority state — server-driven */}
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <AuthorityState check={authority} />
        {acceptBlockedReason ? (
          <Text variant="caption" muted>
            {acceptBlockedReason}
          </Text>
        ) : null}
      </section>

      {/* 6. Lineage timeline */}
      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Text variant="caption" muted>
          Lineage
        </Text>
        {candidate.lifecycle_events.length === 0 ? (
          <EmptyState>No lifecycle events recorded yet.</EmptyState>
        ) : (
          <ol
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: 8,
              borderLeft: "2px solid var(--wg-line)",
              paddingLeft: 12,
            }}
          >
            {candidate.lifecycle_events.map((evt, i) => (
              <li
                key={`${evt.kind}-${i}`}
                style={{ display: "flex", flexDirection: "column", gap: 2 }}
              >
                <Text variant="caption" muted>
                  {evt.at}
                </Text>
                <Text variant="body">
                  {evt.kind}
                  {evt.actor_user_id
                    ? ` · user:${evt.actor_user_id.slice(0, 8)}`
                    : ""}
                </Text>
                {evt.note ? (
                  <Text variant="caption" muted>
                    {evt.note}
                  </Text>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* Feedback strip — bilingual via i18n */}
      {feedback ? (
        <Card accent={feedback.kind === "success" ? "ok" : "amber"}>
          <Text variant="body">{feedback.message}</Text>
        </Card>
      ) : null}

      {/* 7. Actions — enabled state sourced from authority.allowed_actions */}
      <footer
        data-testid="memory-review-actions"
        style={{
          position: "sticky",
          bottom: 0,
          paddingTop: 12,
          borderTop: "1px solid var(--wg-line)",
          background: "var(--wg-surface)",
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          flexWrap: "wrap",
        }}
      >
        <Button
          data-testid="memory-action-reopen"
          variant="ghost"
          size="sm"
          onClick={() => void runAction("reopen")}
          disabled={!actionEnabled("reopen")}
        >
          {pending === "reopen" ? "…" : t("actions.reopen")}
        </Button>
        <Button
          data-testid="memory-action-defer"
          variant="ghost"
          size="sm"
          onClick={() => void runAction("defer")}
          disabled={!actionEnabled("defer")}
        >
          {pending === "defer" ? "…" : t("actions.defer")}
        </Button>
        <Button
          data-testid="memory-action-reject"
          variant="amber"
          size="sm"
          onClick={() => void runAction("reject")}
          disabled={!actionEnabled("reject")}
        >
          {pending === "reject" ? "…" : t("actions.reject")}
        </Button>
        {/* RW-3.5 safety — Revise button removed entirely. Until the
            backend's accept_candidate accepts a revision body, the
            FE has no honest path for "I edited the proposed atom and
            that edit will persist." The button stayed visible after
            RW-3 as a TODO; that's exactly the misleading affordance
            the safety pass closes. The local revisedAtom state is
            also gone — the rendered atom shows the AI distillation
            verbatim. */}
        <Button
          data-testid="memory-action-accept"
          variant="primary"
          size="md"
          onClick={() => void runAction("accept")}
          disabled={!actionEnabled("accept")}
          title={acceptBlockedReason ?? undefined}
        >
          {pending === "accept" ? t("actions.accepting") : t("actions.accept")}
        </Button>
      </footer>
    </div>
  );
}

// Compat re-exports for any caller that previously imported from
// MemoryReviewDrawer. The canonical home is ./memoryCandidateActions.
export { postCandidateAction } from "./memoryCandidateActions";
export type {
  ActionResult,
  CandidateAction,
} from "./memoryCandidateActions";
