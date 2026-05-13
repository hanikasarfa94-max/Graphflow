"use client";

// FlowDrawer — body for `useDrawer().open({ type: 'flow_request', ... })`.
//
// Phase C scaffold (2026-05-13). Rendered inside the shared DrawerHost
// chrome — this file owns the body only (header text, sections, sticky
// CTA footer). The host owns the panel + scrim + ESC + close button.
//
// Doctrine — when Send succeeds, the API returns a
// memory_candidate_prompt. We do NOT auto-accept the candidate. We
// route the user to MemoryPromptDrawer (review / skip / later) per
// DESIGN_LOCK.md invariant: "Flow acceptance does not auto-accept
// memory."
//
// Phase B.2 swap-in: replace useFlowRequest() with a real fetch +
// useFlowRequestSend() with the actual POST /api/flow-requests/:id/send
// and POST /api/flow-requests/:id/respond mutators.

import { useState } from "react";

import { Button, Card, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

import { AuthorityState } from "./AuthorityState";
import type { FlowRequestDetail } from "./types";

// TODO(phase-b.2): replace with real
//   `GET /api/flow-requests/:id`
// Phase C returns a deterministic stub keyed by id so the surface can
// be eyeballed in isolation.
function useFlowRequest(id: string): FlowRequestDetail {
  return {
    id,
    type: "confirm",
    status: "awaiting_response",
    requester: { id: "user_mei", display_name: "Mei" },
    framing:
      "Confirming Q3 launch date moves to September 18. This blocks the marketing schedule lock; please respond before EOD Thursday.",
    attachments: [
      { kind: "doc", id: "doc_launch_plan", label: "Launch plan v4" },
      { kind: "topic", id: "topic_launch_date", label: "Topic: launch date" },
    ],
    authority_check: {
      can_accept: true,
      required_roles: ["approver"],
      user_roles: ["approver"],
      allowed_actions: ["accept", "decline", "counter", "escalate"],
    },
  };
}

// TODO(phase-b.2): replace with real
//   `POST /api/flow-requests/:id/respond`
// returning the memory_candidate_prompt payload. Phase C fakes a
// "yes there's a candidate" response so the prompt drawer can be
// exercised end-to-end without the backend.
function useFlowRequestSend(): (id: string) => Promise<{
  has_candidate: boolean;
  candidate_id: string;
}> {
  return async (id: string) => {
    // Simulate network so the wg-motion-flow-send class has a beat.
    await new Promise((r) => setTimeout(r, 220));
    return { has_candidate: true, candidate_id: `memcand_for_${id}` };
  };
}

export function FlowDrawer({ flow_id }: { flow_id: string }) {
  const drawer = useDrawer();
  const flow = useFlowRequest(flow_id);
  const send = useFlowRequestSend();

  const [response, setResponse] = useState("");
  const [sending, setSending] = useState(false);
  const [animating, setAnimating] = useState(false);

  async function handleSend() {
    if (sending) return;
    setSending(true);
    setAnimating(true);
    try {
      const result = await send(flow.id);
      // v3 motion moment #3 — flow send exit animation runs on the
      // header element via the wg-motion-flow-send class.
      if (result.has_candidate) {
        // Doctrine — open MemoryPromptDrawer, never auto-accept.
        drawer.open({
          type: "memory_prompt",
          props: { candidate_id: result.candidate_id },
        });
      } else {
        drawer.close();
      }
    } finally {
      setSending(false);
      setAnimating(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <header
        className={animating ? "wg-motion-flow-send" : undefined}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <Tag tone="accent">{flow.type}</Tag>
        <Tag tone="neutral">{flow.status}</Tag>
        <Text variant="caption" muted>
          from {flow.requester.display_name}
        </Text>
      </header>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Text variant="caption" muted>
          Framing
        </Text>
        <Text as="p" variant="body">
          {flow.framing}
        </Text>
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Text variant="caption" muted>
          Attachments
        </Text>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {flow.attachments.map((a) => (
            <Text key={a.id} variant="mono">
              {a.kind}:{a.id} — {a.label}
            </Text>
          ))}
        </div>
      </section>

      <AuthorityState check={flow.authority_check} />

      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Text variant="caption" muted>
          Your response
        </Text>
        <textarea
          value={response}
          onChange={(e) => setResponse(e.target.value)}
          placeholder="Edit before sending. The Membrane will review what you write here."
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
      </section>

      <Card variant="sunk">
        <Text variant="caption" muted>
          Memory crystallization is a separate decision. Sending this
          response does not accept any memory atom.
        </Text>
      </Card>

      {/* Sticky CTA footer — DESIGN.md §Drawers: actions are always at
          the bottom and visually anchored. */}
      <footer
        style={{
          position: "sticky",
          bottom: 0,
          marginTop: 4,
          paddingTop: 12,
          borderTop: "1px solid var(--wg-line)",
          background: "var(--wg-surface)",
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          flexWrap: "wrap",
        }}
      >
        <Button variant="ghost" size="md" onClick={() => drawer.close()}>
          Decline
        </Button>
        <Button variant="amber" size="md" onClick={() => drawer.close()}>
          Escalate
        </Button>
        <Button variant="ghost" size="md" onClick={() => drawer.close()}>
          Counter
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={handleSend}
          disabled={sending}
        >
          {sending ? "Sending…" : "Send"}
        </Button>
      </footer>
    </div>
  );
}
