"use client";

// FlowTable — the flow packet table that lives inside <FlowCenter>.
//
// Phase C scaffold (2026-05-13). Mock rows live at the top of this file
// (MOCK_ROWS) so the surface renders end-to-end while the wire contract
// stabilizes. Each row reflects one of the eight FlowRequestType values
// from API_CONTRACT.md so the visual grammar (type pill + status tag +
// Next button) gets exercised across the matrix.
//
// Phase B.2 swap-in: replace MOCK_ROWS + useFlowTableRows() with
//   `GET /api/flow-requests?scope_id=<active>&bucket=<needs_me|waiting|...>`
// returning the same row shape (or a typed wire object that maps 1:1).
//
// The "Next" column always opens FlowDrawer via useDrawer() — no
// inline state mutation, no business logic. Thin-router pattern in the
// frontend equivalent.

import { Button, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

import type { FlowRequestType, FlowRequestStatus } from "./types";

interface FlowTableRow {
  id: string;
  type: FlowRequestType;
  title: string;
  source: string;
  target: string;
  requester: string;
  authority: string;
  evidenceCount: number;
  status: FlowRequestStatus;
}

// TODO(phase-b.2): replace with rows from
//   `GET /api/flow-requests?scope_id=...`
// Stub data — every FlowRequestType present at least once so the
// styling matrix renders.
const MOCK_ROWS: FlowTableRow[] = [
  {
    id: "flow_001",
    type: "confirm",
    title: "Confirm Q3 launch date moves to Sep 18",
    source: "topic:topic_launch_date",
    target: "user:alex",
    requester: "Mei",
    authority: "project_owner",
    evidenceCount: 4,
    status: "awaiting_response",
  },
  {
    id: "flow_002",
    type: "review",
    title: "Review pricing memo before exec sync",
    source: "doc:doc_pricing_v3",
    target: "user:jess",
    requester: "Ravi",
    authority: "reviewer",
    evidenceCount: 2,
    status: "in_membrane",
  },
  {
    id: "flow_003",
    type: "handoff",
    title: "Handoff onboarding flow to growth team",
    source: "task:task_onboarding",
    target: "team:growth",
    requester: "Alex",
    authority: "assignee",
    evidenceCount: 6,
    status: "draft",
  },
  {
    id: "flow_004",
    type: "approval",
    title: "Approve $40k vendor contract renewal",
    source: "doc:doc_vendor_renewal",
    target: "user:vp_ops",
    requester: "Jess",
    authority: "approver",
    evidenceCount: 3,
    status: "awaiting_response",
  },
  {
    id: "flow_005",
    type: "clarification",
    title: "Clarify scope: web only, or web + mobile?",
    source: "topic:topic_scope_q",
    target: "user:pm_lead",
    requester: "Ravi",
    authority: "requester",
    evidenceCount: 1,
    status: "responded",
  },
  {
    id: "flow_006",
    type: "delegate",
    title: "Delegate compliance review to Priya",
    source: "task:task_sso_audit",
    target: "user:priya",
    requester: "Mei",
    authority: "project_owner",
    evidenceCount: 2,
    status: "accepted",
  },
];

const STATUS_TONE: Record<
  FlowRequestStatus,
  "neutral" | "accent" | "amber" | "ok" | "danger"
> = {
  draft: "neutral",
  awaiting_response: "accent",
  in_membrane: "amber",
  responded: "neutral",
  accepted: "ok",
  declined: "danger",
};

const STATUS_LABEL: Record<FlowRequestStatus, string> = {
  draft: "Draft",
  awaiting_response: "Awaiting",
  in_membrane: "In Membrane",
  responded: "Responded",
  accepted: "Accepted",
  declined: "Declined",
};

// TODO(phase-b.2): replace with a real data hook backed by SWR / RQ.
function useFlowTableRows(): FlowTableRow[] {
  return MOCK_ROWS;
}

export function FlowTable() {
  const rows = useFlowTableRows();
  const drawer = useDrawer();

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "var(--wg-fs-body)",
          fontFamily: "var(--wg-font-sans)",
        }}
      >
        <thead>
          <tr
            style={{
              textAlign: "left",
              borderBottom: "1px solid var(--wg-line)",
              background: "var(--wg-surface-sunk)",
            }}
          >
            <Th>Source → Target</Th>
            <Th>Title</Th>
            <Th>Requester</Th>
            <Th>Authority</Th>
            <Th>Evidence</Th>
            <Th>Status</Th>
            <Th>Next</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              style={{ borderBottom: "1px solid var(--wg-line-soft)" }}
            >
              <Td>
                <Text variant="caption" muted>
                  {row.source}
                </Text>
                <br />
                <Text variant="caption" muted>
                  → {row.target}
                </Text>
              </Td>
              <Td>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <Tag tone="accent">{row.type}</Tag>
                  <Text variant="body">{row.title}</Text>
                </div>
              </Td>
              <Td>
                <Text variant="body">{row.requester}</Text>
              </Td>
              <Td>
                <Text variant="caption" muted>
                  {row.authority}
                </Text>
              </Td>
              <Td>
                <Text variant="mono">{row.evidenceCount}</Text>
              </Td>
              <Td>
                <Tag tone={STATUS_TONE[row.status]}>
                  {STATUS_LABEL[row.status]}
                </Tag>
              </Td>
              <Td>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    drawer.open({
                      type: "flow_request",
                      props: { flow_id: row.id },
                    })
                  }
                >
                  Open
                </Button>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th
      style={{
        padding: "10px 14px",
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        fontFamily: "var(--wg-font-mono)",
        color: "var(--wg-ink-soft)",
        fontWeight: 600,
      }}
    >
      {children}
    </th>
  );
}

function Td({ children }: { children: React.ReactNode }) {
  return (
    <td
      style={{
        padding: "12px 14px",
        verticalAlign: "top",
      }}
    >
      {children}
    </td>
  );
}
