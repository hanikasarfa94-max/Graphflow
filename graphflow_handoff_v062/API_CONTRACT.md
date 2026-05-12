# API_CONTRACT.md

## Proposal / action split

AI Assistance creates proposals. Actions mutate state.

```ts
interface AIAssistanceResponse { proposal: Proposal; mutates_state: false }
```

## Authority pattern

Server computes permissions. Frontend renders allowed actions.

```ts
interface AuthorityCheck {
  can_accept: boolean;
  required_roles: AuthorityRole[];
  user_roles: AuthorityRole[];
  allowed_actions: AllowedAction[];
}
```

Use this for memory candidate acceptance, flow acceptance, task promotion, document publish, and topic resolution.

## Scope APIs

`GET /api/scopes`

`GET /api/user/active-scope`

`POST /api/user/active-scope`

```ts
type RetrievalScopeMode = "current_focus" | "all_accessible" | "no_focus";
```

## My AI APIs

`GET /api/my-ai/landing?scope_id=scope_tikhub`

Returns grounded re-entry items and Ready to Share drafts. Grounded items must be real objects, not freeform LLM summaries.

`POST /api/my-ai/messages`

Returns assistant message plus proposals.

## Proposal APIs

```ts
type ProposalType =
  | "routing_suggestion"
  | "task_candidate"
  | "document_draft"
  | "topic_suggestion"
  | "memory_candidate"
  | "impact_analysis"
  | "capability_explanation"
  | "topic_closure";
```

`GET /api/proposals/:proposalId`

`POST /api/proposals/:proposalId/accept`

`POST /api/proposals/:proposalId/dismiss`

`POST /api/proposals/:proposalId/mark-stale`

## Conversations

```ts
type ConversationType = "direct" | "room" | "topic";
```

`GET /api/conversations?scope_id=scope_tikhub`

No-duplication rule: Recent = DMs + Rooms; Active Topics = Topics.

`GET /api/conversations/:conversationId` should include initial `right_rail`.

`POST /api/conversations/:conversationId/messages`

## Topics

```ts
type TopicStatus = "open" | "needs_input" | "waiting" | "resolved" | "archived";
```

`POST /api/topics` creates a topic from selected messages / context.

`PATCH /api/topics/:topicId/status`

`POST /api/topics/:topicId/propose-closure` returns proposal only.

## Flow Requests

```ts
type FlowRequestType = "confirm" | "feedback" | "review" | "clarification" | "handoff" | "accept_task" | "delegate" | "approval";
```

`POST /api/flow-requests/draft`

`PATCH /api/flow-requests/:id/attachments`

`POST /api/flow-requests/:id/send`

`POST /api/flow-requests/:id/respond`

Flow response must not auto-open or auto-accept memory. It may return:

```json
{
  "memory_candidate_prompt": {
    "has_candidate": true,
    "candidate_id": "memcand_001",
    "actions": ["review", "skip", "later"]
  }
}
```

`POST /api/flow-responses/:id/generate-memory-candidate` enables Skip reversal.

## Memory Candidate / Membrane

```ts
type MemoryCandidateStatus =
  | "draft"
  | "prompted"
  | "deferred"
  | "review_pending"
  | "accepted"
  | "rejected"
  | "skipped"
  | "reopened"
  | "expired"
  | "superseded";
```

`GET /api/memory-candidates/:id` must include:

- verbatim source
- AI extracted claim
- compression analysis
- compression warnings
- proposed memory atom
- authority check
- affected objects
- lifecycle events

Compression analysis example:

```json
{
  "compression_analysis": {
    "status": "warnings_found",
    "warning_count": 2,
    "method": ["rule_based", "ai_semantic_check"],
    "caveat": "No warning does not guarantee faithful distillation."
  }
}
```

Unauthorized accept returns 403 with required roles and allowed actions.

`POST /api/memory-candidates/:id/accept`

`POST /api/memory-candidates/:id/defer`

`POST /api/memory-candidates/:id/reopen`

`POST /api/memory-candidates/:id/reject`

## Memory Atom Outbound Lineage

`GET /api/memory-atoms/:id/citations` returns cited_by and downstream_dependencies.

## Tasks

```ts
type TaskRecognitionPolicy = "none" | "assignee_accept" | "project_owner_confirm" | "flow_required" | "review_required";
```

`GET /api/tasks?scope_id=scope_tikhub&view=my_tasks`

`POST /api/tasks/candidates` context-born candidate.

`POST /api/tasks/:id/promote` requires recognition policy.

## Documents / KB

`GET /api/documents?scope_id=scope_tikhub&type=all`

`GET /api/scopes/:scopeId/project-brief`

`POST /api/documents/:id/publish` may return memory candidates; never accepted memory.

## Right Rail

Primary object responses should include initial `right_rail`.

`GET /api/right-rail?surface=task&object_id=task_123` is refresh-only.

## AI Assistance

`POST /api/ai-assistance/run` must return `mutates_state: false`.

## Create Menu

`GET /api/create-menu` returns only conversation, document, upload, project_scope. It must expose excluded_direct_creations: task, topic, flow_request, memory.
