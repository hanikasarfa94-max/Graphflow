"use client";

// CitedClaimList — Phase 1.B provenance chips.
//
// Renders an edge-LLM claim block: one row per {text, citations[]} claim.
// Citation chips link to /projects/[id]/nodes/[nodeId] so the user can
// pop out to the cited decision / task / risk etc. in one click.
//
// Uncited claims (empty `citations`) render in a muted ink — never hidden,
// always legible. The whole block renders nothing when `claims` is
// empty so legacy turns (no claims at all) fall back to the caller's
// plain <body> display.

import Link from "next/link";
import type { CSSProperties } from "react";

import type { CitedClaim, CitationKind } from "@/lib/api";

const CITATION_ABBREV: Record<string, string> = {
  decision: "D",
  task: "T",
  risk: "R",
  deliverable: "DL",
  goal: "G",
  milestone: "M",
  commitment: "C",
  wiki_page: "wiki",
  kb: "kb",
};

function citationLabel(kind: CitationKind, nodeId: string): string {
  const prefix = CITATION_ABBREV[kind] ?? kind;
  const shortId = nodeId.length > 8 ? `${nodeId.slice(0, 6)}…` : nodeId;
  // wiki/kb use the slash form the spec calls out: [wiki/combat], [kb/...].
  if (kind === "wiki_page" || kind === "kb") {
    return `${prefix}/${shortId}`;
  }
  return `${prefix}#${shortId}`;
}

const claimRowStyle: CSSProperties = {
  display: "flex",
  gap: 6,
  alignItems: "baseline",
  flexWrap: "wrap",
  marginBottom: 4,
};

const citedTextStyle: CSSProperties = {
  color: "var(--wg-ink)",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
};

// Uncited claims stay legible but visually weaker — we piggy-back on
// the existing `--wg-ink-faint` token to match ambient-signal muting.
const uncitedTextStyle: CSSProperties = {
  color: "var(--wg-ink-faint)",
  fontStyle: "italic",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
};

const chipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "1px 6px",
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  color: "var(--wg-ink-soft)",
  background: "var(--wg-surface-sunk, #faf8f4)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  textDecoration: "none",
  lineHeight: 1.4,
};

type Props = {
  projectId: string;
  claims: CitedClaim[];
};

export function CitedClaimList({ projectId, claims }: Props) {
  if (!claims || claims.length === 0) return null;
  return (
    <div data-testid="cited-claim-list" style={{ marginTop: 2 }}>
      {claims.map((claim, idx) => {
        const uncited = !claim.citations || claim.citations.length === 0;
        return (
          <div
            key={idx}
            style={claimRowStyle}
            data-testid="cited-claim"
            data-uncited={uncited ? "true" : "false"}
          >
            <span style={uncited ? uncitedTextStyle : citedTextStyle}>
              {claim.text}
            </span>
            {(claim.citations || []).map((c, cIdx) => (
              <Link
                key={`${c.node_id}-${cIdx}`}
                href={`/projects/${projectId}/nodes/${c.node_id}`}
                className="wg-motion-citation-glow"
                style={{
                  ...chipStyle,
                  animationDelay: `${(idx * 2 + cIdx) * 80}ms`,
                }}
                data-testid="citation-chip"
                data-node-id={c.node_id}
                data-kind={c.kind}
              >
                [{citationLabel(c.kind, c.node_id)}]
              </Link>
            ))}
          </div>
        );
      })}
    </div>
  );
}

// Pure helper exported for snapshot / parser tests — matches the href
// format the chip renders.
export function citationHref(projectId: string, nodeId: string): string {
  return `/projects/${projectId}/nodes/${nodeId}`;
}
