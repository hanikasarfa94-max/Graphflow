// Feature-scoped re-exports of the flow types that already live in
// `@/lib/flows`. Phase E (Architecture Organization Pass v1) keeps the
// runtime client + types in `lib/flows.ts` (the spec is "keep it or
// move whole" and right now keeping is safer); this file just gives
// callers inside `features/flows/` an ergonomic single import path.
//
// Add new feature-local types here only when they don't belong on the
// wire contract — anything the BE projection emits should stay in
// `lib/flows.ts` so the typed boundary stays in one place.

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
} from "@/lib/flows";
