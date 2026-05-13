"use client";

// MemoryReviewDrawer — the full Membrane review surface. The hardest
// doctrine UI in the product. Renders the entire memory lineage and
// gates acceptance on server-computed authority.
//
// Phase RW-2.2 (2026-05-13): read path is live. The drawer fetches
// the candidate via `GET /api/memory-candidates/:id` on mount
// (MembraneService.get_candidate_full_detail) and renders the wire
// shape directly. Compression caveat, authority check, lineage all
// come from the server. Mock useMemoryCandidate() is gone.
//
// Mutation actions (accept / revise / reject / defer / skip / reopen)
// stay no-op stubs per the RW-2 brief — "no new mutation behavior
// until read path is verified." Wiring them comes in RW-3.
//
// DESIGN_LOCK.md invariants honored:
//   #6  Flow acceptance does not auto-accept memory.       ← prompt → review handoff
//   #7  Memory crystallization is a separate decision.     ← acceptance is its own action
//   #8  Memory acceptance requires server-side authority.  ← Accept disabled if !can_accept
//   #9  Memory candidates must preserve lineage.           ← VerbatimSource → distillation → revision → accepted
//
// API surface:
//   GET  /api/memory-candidates/:id          ← live (RW-2.2)
//   POST /api/memory-candidates/:id/accept   ← Phase RW-3
//   POST /api/memory-candidates/:id/defer    ← Phase RW-3
//   POST /api/memory-candidates/:id/reject   ← Phase RW-3
//   POST /api/memory-candidates/:id/reopen   ← Phase RW-3

import { useEffect, useState } from "react";

import { Button, Card, EmptyState, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";
import { ApiError, api } from "@/lib/api";

import { AuthorityState } from "./AuthorityState";
import type { MemoryCandidate } from "./types";

type FetchState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; candidate: MemoryCandidate };

function useMemoryCandidate(id: string): FetchState {
  const [state, setState] = useState<FetchState>({ status: "loading" });
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
  }, [id]);
  return state;
}

// Mutation handlers stay no-op until RW-3 — the brief locks the read
// path first. The hook exists so the action footer doesn't have to
// branch on "is mutation wired" vs the disabled-by-authority case.
function useMemoryAction(): (
  action: "accept" | "revise" | "reject" | "defer" | "skip" | "reopen",
  id: string,
  revisedAtom?: string,
) => Promise<void> {
  return async () => {
    // TODO(RW-3): POST to the matching /api/memory-candidates/:id/<action>
    // endpoint (accept / defer / reject / reopen are live in
    // memory_candidates.py; skip + revise are Phase B.3 follow-ups).
    await new Promise((r) => setTimeout(r, 120));
  };
}

export function MemoryReviewDrawer({ candidate_id }: { candidate_id: string }) {
  const drawer = useDrawer();
  const fetchState = useMemoryCandidate(candidate_id);
  const act = useMemoryAction();

  if (fetchState.status === "loading") {
    return (
      <div style={{ padding: 24 }}>
        <Text variant="caption" muted>
          Loading memory candidate…
        </Text>
      </div>
    );
  }

  if (fetchState.status === "error") {
    return (
      <div style={{ padding: 24 }}>
        <EmptyState>{fetchState.message}</EmptyState>
      </div>
    );
  }

  return (
    <MemoryReviewBody
      candidate={fetchState.candidate}
      candidate_id={candidate_id}
      act={act}
      onClose={drawer.close}
    />
  );
}

function MemoryReviewBody({
  candidate,
  candidate_id,
  act,
  onClose,
}: {
  candidate: MemoryCandidate;
  candidate_id: string;
  act: ReturnType<typeof useMemoryAction>;
  onClose: () => void;
}) {
  const [revising, setRevising] = useState(false);
  const [revisedAtom, setRevisedAtom] = useState(
    candidate.proposed_memory_atom.claim,
  );
  const [accepting, setAccepting] = useState(false);
  const [acceptedAnim, setAcceptedAnim] = useState(false);

  const authority = candidate.authority_check;
  const acceptBlockedReason = authority.can_accept
    ? null
    : `Request review from a ${authority.required_roles[0] ?? "reviewer"}.`;

  // First lifecycle event ≈ verbatim capture. Used to surface a
  // timestamp on the verbatim block since the wire shape no longer
  // carries an inline timestamp.
  const verbatimAt = candidate.lifecycle_events[0]?.at ?? null;

  async function handleAccept() {
    if (!authority.can_accept || accepting) return;
    setAccepting(true);
    setAcceptedAnim(true);
    try {
      await act("accept", candidate_id, revising ? revisedAtom : undefined);
      // Brief beat so the v3 motion moment #2 plays before we close.
      await new Promise((r) => setTimeout(r, 260));
      onClose();
    } finally {
      setAccepting(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
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

      {/* 4. Proposed memory atom — with revise affordance */}
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <Text variant="caption" muted>
            Proposed memory atom · {candidate.proposed_memory_atom.tier}
          </Text>
          <Button
            variant="link"
            size="sm"
            onClick={() => setRevising((r) => !r)}
          >
            {revising ? "Cancel revision" : "Revise"}
          </Button>
        </div>
        <Card
          accent="accent"
          // v3 motion moment #2 — fires once on acceptance.
          {...(acceptedAnim ? { "data-motion": "accept" } : {})}
        >
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
            {revising ? (
              <textarea
                value={revisedAtom}
                onChange={(e) => setRevisedAtom(e.target.value)}
                rows={5}
                style={{
                  width: "100%",
                  padding: 10,
                  borderRadius: "var(--wg-radius)",
                  border: "1px solid var(--wg-line)",
                  background: "var(--wg-surface)",
                  fontFamily: "var(--wg-font-sans)",
                  fontSize: "var(--wg-fs-body)",
                  color: "var(--wg-ink)",
                  lineHeight: "var(--wg-lh-normal)",
                  resize: "vertical",
                }}
              />
            ) : (
              <Text as="p" variant="body">
                {revisedAtom || "(no claim)"}
              </Text>
            )}
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

      {/* 7. Six actions — mutation wiring lands in RW-3. */}
      <footer
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
          variant="ghost"
          size="sm"
          onClick={() => act("reopen", candidate_id).then(() => onClose())}
        >
          Reopen
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => act("skip", candidate_id).then(() => onClose())}
        >
          Skip
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => act("defer", candidate_id).then(() => onClose())}
        >
          Defer
        </Button>
        <Button
          variant="amber"
          size="sm"
          onClick={() => act("reject", candidate_id).then(() => onClose())}
        >
          Reject
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setRevising(true)}
          disabled={revising}
        >
          Revise
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={handleAccept}
          disabled={!authority.can_accept || accepting}
          title={acceptBlockedReason ?? undefined}
        >
          {accepting ? "Accepting…" : "Accept"}
        </Button>
      </footer>
    </div>
  );
}
