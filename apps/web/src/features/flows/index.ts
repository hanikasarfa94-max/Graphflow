// Public surface of the `features/flows` feature module. Phase E pilot
// of the Architecture Organization Pass v1 — only the two extracted
// view components live here so far. Hooks (`useFlowBuckets`), the
// popover wrapper, and finer-grained action / evidence subcomponents
// are explicitly out of scope for this pass; they'll land in follow-up
// passes once the pattern proves out on the load-bearing surface.
//
// API client + wire types continue to live in `@/lib/flows`. Nothing
// in `features/flows/` instantiates an LLM client, owns business
// logic, or talks to the BE outside that boundary — see CLAUDE.md
// §"Architectural invariants".

export { FlowEmptyState } from "./components/FlowEmptyState";
export type { FlowEmptyStateProps } from "./components/FlowEmptyState";

export { FlowPacketRow } from "./components/FlowPacketRow";
export type { FlowPacketRowProps } from "./components/FlowPacketRow";

// Re-export the wire-shape types so callers inside this feature can
// import them without reaching into `@/lib/flows` directly. The
// re-export is intentional duplication of `types.ts`'s surface — both
// paths stay valid.
export type {
  EvidencePacket,
  FlowAction,
  FlowActionBody,
  FlowActionKind,
  FlowActionResponse,
  FlowBucket,
  FlowEvent,
  FlowPacket,
  FlowPacketStatus,
  FlowRecipeId,
  FlowRef,
  FlowsListParams,
  FlowsListResponse,
  ParticipantInfo,
} from "./types";
