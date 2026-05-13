"use client";

// FlowTable — the flow packet table that lives inside <FlowCenter>.
//
// Phase RW-2.1 (2026-05-13): renders live packets from
// GET /api/flow-requests?scope_id=… (wraps FlowProjectionService).
// MOCK_ROWS + useFlowTableRows() are gone. Each row is a real
// FlowPacket emitted by the projection layer; the recipe + status
// + participant fields come straight from the wire.
//
// The "Open" button still routes through useDrawer() with
// type=flow_request. The drawer body itself remains mock until
// Phase RW-3 — the read path is verified first.

import { Button, EmptyState, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

import type {
  FlowListResponse,
  FlowPacket,
  FlowPacketRecipe,
  FlowPacketStatus,
  FlowParticipant,
} from "./types";

// Recipe → human label. The wire id is machine-stable; the FE picks
// a short readable name for the type pill.
const RECIPE_LABEL: Record<FlowPacketRecipe, string> = {
  ask_with_context: "Route",
  promote_to_memory: "Memory promote",
  promote_task_to_plan: "Task promote",
  crystallize_decision: "Decision",
  manual_create_room: "New room",
  manual_skill_change: "Skill change",
  manual_invite: "Invite",
  review: "Review",
  handoff: "Handoff",
  meeting_metabolism: "Meeting",
};

const STATUS_TONE: Record<
  FlowPacketStatus,
  "neutral" | "accent" | "amber" | "ok" | "danger"
> = {
  active: "accent",
  blocked: "amber",
  completed: "ok",
  rejected: "danger",
  expired: "neutral",
};

function nameFor(
  participants: Record<string, FlowParticipant>,
  user_id: string | null,
): string {
  if (!user_id) return "—";
  const p = participants[user_id];
  if (!p) return user_id.slice(0, 8);
  return p.display_name || p.username || user_id.slice(0, 8);
}

function targetLabel(packet: FlowPacket, participants: Record<string, FlowParticipant>): string {
  const live = packet.current_target_user_ids;
  if (live.length === 0) return "—";
  if (live.length === 1) return nameFor(participants, live[0]);
  return `${nameFor(participants, live[0])} +${live.length - 1}`;
}

function authorityLabel(packet: FlowPacket): string {
  // Authority is a list of user_ids server-side; the table just needs
  // a tone signal ("project_owner" / count). When the v0.6.2
  // AuthorityRole enum is wired (Phase RW-3) we'll resolve a role
  // string; for the read path we surface the raw count.
  const n = packet.authority_user_ids.length;
  if (n === 0) return "—";
  if (n === 1) return "1 authority";
  return `${n} authorities`;
}

export function FlowTable({
  data,
  userId,
}: {
  data: FlowListResponse;
  userId: string;
}) {
  const drawer = useDrawer();

  if (data.packets.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <EmptyState>
          No flow packets in this scope. New packets show up here when
          someone routes a question, promotes a memory candidate,
          handoffs work, or crystallizes a decision.
        </EmptyState>
      </div>
    );
  }

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
            <Th>Type</Th>
            <Th>Title</Th>
            <Th>Source → Target</Th>
            <Th>Authority</Th>
            <Th>Status</Th>
            <Th>Next</Th>
          </tr>
        </thead>
        <tbody>
          {data.packets.map((row) => {
            const sourceName = nameFor(data.participants, row.source_user_id);
            const targetName = targetLabel(row, data.participants);
            const needsMe = row.current_target_user_ids.includes(userId);
            return (
              <tr
                key={row.id}
                style={{ borderBottom: "1px solid var(--wg-line-soft)" }}
              >
                <Td>
                  <Tag tone={needsMe ? "accent" : "neutral"}>
                    {RECIPE_LABEL[row.recipe_id] || row.recipe_id}
                  </Tag>
                </Td>
                <Td>
                  <Text variant="body">{row.title || row.summary || row.id}</Text>
                  {row.intent ? (
                    <>
                      <br />
                      <Text variant="caption" muted>
                        {row.intent}
                      </Text>
                    </>
                  ) : null}
                </Td>
                <Td>
                  <Text variant="caption" muted>
                    {sourceName}
                  </Text>
                  <br />
                  <Text variant="caption" muted>
                    → {targetName}
                  </Text>
                </Td>
                <Td>
                  <Text variant="caption" muted>
                    {authorityLabel(row)}
                  </Text>
                </Td>
                <Td>
                  <Tag tone={STATUS_TONE[row.status]}>{row.status}</Tag>
                  {row.stage && row.stage !== row.status ? (
                    <>
                      <br />
                      <Text variant="caption" muted>
                        {row.stage}
                      </Text>
                    </>
                  ) : null}
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
            );
          })}
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
