"use client";

// MemoryReviewDrawer — the full Membrane review surface. The hardest
// doctrine UI in the product. Renders the entire memory lineage and
// gates acceptance on server-computed authority.
//
// DESIGN_LOCK.md invariants honored here:
//   #6  Flow acceptance does not auto-accept memory.       ← prompt → review handoff
//   #7  Memory crystallization is a separate decision.     ← acceptance is its own action
//   #8  Memory acceptance requires server-side authority.  ← Accept disabled if !can_accept
//   #9  Memory candidates must preserve lineage.           ← VerbatimSource → distillation → revision → accepted
//
// Sections, top to bottom (per API_CONTRACT.md GET /api/memory-candidates/{id}):
//   1. VerbatimSource — author byline + cited block
//   2. AIExtractedClaim — italic distillation
//   3. CompressionAnalysis — amber Card, caveat string verbatim
//   4. ProposedMemoryAtom — editable in place
//   5. AuthorityState — read from server
//   6. LineageTimeline — vertical event list
//   7. Six actions: Accept / Revise / Reject / Defer / Skip / Reopen
//
// Accept fires the wg-motion-memory-accept class on the proposed-atom
// card (v3 motion moment #2). Accept is HARD-DISABLED when
// authority.can_accept === false. There is no client-side override —
// the disabled state is sourced from the server response.
//
// Phase B.2 swap-in: replace useMemoryCandidate() with real
//   `GET /api/memory-candidates/:id`
// and useMemoryAction() with the five POST mutators.

import { useState } from "react";

import { Button, Card, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

import { AuthorityState } from "./AuthorityState";
import type { MemoryCandidate } from "./types";

// TODO(phase-b.2): replace with real
//   `GET /api/memory-candidates/:id`
// Stub mirrors the wire contract exactly — including the doctrine
// caveat string, which must render verbatim wherever surfaced.
function useMemoryCandidate(id: string): MemoryCandidate {
  return {
    id,
    status: "review_pending",
    verbatim_source: {
      author: "Mei",
      timestamp: "2026-05-12T14:33:00Z",
      text: "Q3 launch is now September 18. Marketing schedule is locked downstream — anything before then is at risk.",
      citation_url: `/conversations/topic_launch_date#msg_4218`,
    },
    ai_extracted_claim:
      "The team has committed Q3 launch to September 18, blocking marketing schedule changes prior to that date.",
    compression_analysis: {
      status: "warnings_found",
      warning_count: 2,
      method: ["rule_based", "ai_semantic_check"],
      // Verbatim doctrine string from API_CONTRACT.md.
      caveat: "No warning does not guarantee faithful distillation.",
    },
    proposed_memory_atom:
      "Q3 launch date is locked to 2026-09-18. Marketing schedule depends on this; predecessors should not slip past 2026-09-04.",
    authority_check: {
      // Toggle this to false to manually verify the disabled-Accept
      // path renders correctly. Phase B.2 reads this from the server.
      can_accept: true,
      required_roles: ["project_owner"],
      user_roles: ["project_owner", "approver"],
      allowed_actions: ["accept", "revise", "reject", "defer", "skip", "reopen"],
    },
    affected_objects: [
      { kind: "task", id: "task_marketing_calendar", label: "Marketing calendar" },
      { kind: "doc", id: "doc_launch_plan", label: "Launch plan v4" },
    ],
    lifecycle_events: [
      {
        kind: "verbatim_captured",
        actor: "Mei",
        at: "2026-05-12T14:33:00Z",
      },
      {
        kind: "ai_distilled",
        actor: "membrane.agent",
        at: "2026-05-12T14:33:05Z",
      },
    ],
  };
}

// TODO(phase-b.2): replace with real POSTs against
//   /api/memory-candidates/:id/{accept,reject,defer,reopen}
function useMemoryAction(): (
  action: "accept" | "revise" | "reject" | "defer" | "skip" | "reopen",
  id: string,
  revisedAtom?: string,
) => Promise<void> {
  return async () => {
    await new Promise((r) => setTimeout(r, 200));
  };
}

export function MemoryReviewDrawer({ candidate_id }: { candidate_id: string }) {
  const drawer = useDrawer();
  const candidate = useMemoryCandidate(candidate_id);
  const act = useMemoryAction();

  const [revising, setRevising] = useState(false);
  const [revisedAtom, setRevisedAtom] = useState(candidate.proposed_memory_atom);
  const [accepting, setAccepting] = useState(false);
  const [acceptedAnim, setAcceptedAnim] = useState(false);

  const authority = candidate.authority_check;
  const acceptBlockedReason = authority.can_accept
    ? null
    : `Request review from a ${authority.required_roles[0] ?? "reviewer"}.`;

  async function handleAccept() {
    if (!authority.can_accept || accepting) return;
    setAccepting(true);
    setAcceptedAnim(true);
    try {
      await act("accept", candidate_id, revising ? revisedAtom : undefined);
      // Brief beat so the v3 motion moment #2 plays before we close.
      await new Promise((r) => setTimeout(r, 260));
      drawer.close();
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
            {candidate.verbatim_source.author} ·{" "}
            {candidate.verbatim_source.timestamp}
          </Text>
          <Text
            as="p"
            variant="mono"
            style={{ marginTop: 6, whiteSpace: "pre-wrap" }}
          >
            {candidate.verbatim_source.text}
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
          {candidate.ai_extracted_claim}
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
          </div>
        </Card>
      </section>

      {/* 4. Proposed memory atom — with revise affordance */}
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <Text variant="caption" muted>
            Proposed memory atom
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
                {revisedAtom}
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
                {evt.kind} · {evt.actor}
              </Text>
            </li>
          ))}
        </ol>
      </section>

      {/* 7. Six actions */}
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
          onClick={() => act("reopen", candidate_id).then(() => drawer.close())}
        >
          Reopen
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => act("skip", candidate_id).then(() => drawer.close())}
        >
          Skip
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => act("defer", candidate_id).then(() => drawer.close())}
        >
          Defer
        </Button>
        <Button
          variant="amber"
          size="sm"
          onClick={() => act("reject", candidate_id).then(() => drawer.close())}
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
