# Membrane Agent Review Spec

Status: draft for implementation
Date: 2026-05-05

## 1. Problem

GraphFlow's Membrane is currently a boundary framework, but internal candidates are mostly reviewed by fixed Python checks. That is not enough for the product thesis.

The real invariant is:

> Anything that becomes shared team context must pass through a semantic boundary before it can influence other humans or agents.

Today this is only partially true.

External ingest already uses `MembraneAgent.classify(...)`, but internal writes such as KB promote, task promote, and decision crystallization mostly use deterministic rules. This lets semantic contradictions enter shared graph state when they are not expressible as duplicate titles, numeric mismatch, or simple budget/status warnings.

## 2. Current Gaps

### 2.1 KB Promote

Current path:

`personal/group candidate -> KbItemService -> MembraneService.review(kind="kb_item_group") -> fixed checks`

Current checks:

- duplicate normalized title
- duplicate title with size divergence -> clarification
- same-topic numeric conflict -> review

Gaps:

- non-numeric contradiction, e.g. "revive is in scope" vs "revive is cut"
- stale note superseded by a newer decision
- candidate contradicts `DecisionRow`
- same topic under different wording with no numeric claim
- "elaborates existing entry" vs "supersedes existing entry" cannot be inferred semantically
- existing polluted `group + published` rows are not audited

### 2.2 Task Promote

Current path:

`personal task -> /api/tasks/{id}/promote -> MembraneService.review(kind="task_promote") -> fixed checks`

Current checks:

- active plan task with same normalized title -> review
- done/cancelled same title -> warning
- estimate overflow -> warning
- existing unstaffed downstream tasks -> warning
- assignee role not covered by skill tags -> warning

Gaps:

- semantic duplicate task with different title
- task contradicts a decision, e.g. "implement revive" after revive was cut
- task relies on polluted or stale KB
- task reopens work that was intentionally closed
- two private tasks from different users converge on the same team work
- "warning only" may be too weak when promotion changes canonical plan state

### 2.3 Decision Crystallization

Current path:

Several services call `MembraneService.review(kind="decision_crystallize")`.

Current behavior:

- advisory only
- always `auto_merge`
- warnings for duplicate-ish title and missing rationale

Gaps:

- contradictory decision can crystallize
- reversal/supersession is not first-class
- decision may conflict with active task/KB state
- no semantic check against prior decisions or dissent
- human gate already happened upstream, but the membrane still should attach conflict warnings or require explicit supersede metadata

### 2.4 Manual Room / Project

`CandidateKind` includes `manual_project` and `manual_room`, but room creation has TODO wiring and review falls through for unknown kinds.

Gaps:

- rooms define attention scope and quorum, so room creation is a governance act
- room membership can change who sees future state
- no Membrane gate currently checks name, purpose, membership, or duplicate room intent

### 2.5 Existing State

Membrane currently runs at write/promote time.

Gaps:

- existing polluted published rows remain published
- retrieval continues to feed them to Edge Agent
- no one-shot audit pass flags old conflicts

## 3. Product Rule

Membrane Agent is the semantic reviewer inside `MembraneService.review(...)`.

It does not write to the database.

It returns a structured review. The service enforces. The caller obeys.

```text
candidate enters
-> deterministic policy checks
-> Membrane Agent semantic review when needed
-> MembraneReview(action, reason, diff, conflicts, warnings)
-> caller mutates row or stages review
```

LLM recommends. MembraneService normalizes and enforces. Domain services mutate.

## 4. Review Actions

Keep the existing four actions:

- `auto_merge`
- `request_review`
- `request_clarification`
- `reject`

Add confidence and evidence internally if useful, but do not widen the public action vocabulary yet.

Recommended internal semantic review result:

```json
{
  "action": "request_review",
  "reason": "candidate_contradicts_existing_memory",
  "diff_summary": "Candidate says revive is in scope; Decision D-12 cut revive from launch scope.",
  "clarify_question": null,
  "conflict_with": ["decision:D-12"],
  "warnings": [],
  "confidence": 0.86
}
```

Map low confidence conservatively:

- low confidence + possible contradiction -> `request_review`
- unclear proposer intent -> `request_clarification`
- obvious unsafe/injection/nonsense -> `reject`
- no meaningful conflict -> `auto_merge`

## 5. Pretext Builder

Do not pass the whole project.

Build a small review packet per candidate kind.

### 5.1 Shared Envelope

```json
{
  "candidate": {
    "kind": "kb_item_group",
    "project_id": "...",
    "proposer_user_id": "...",
    "title": "...",
    "content": "...",
    "metadata": {}
  },
  "policy_context": {
    "allowed_actions": ["auto_merge", "request_review", "request_clarification", "reject"],
    "write_target": "group_kb",
    "shared_context_impact": "will_be_visible_to_project_agents_if_published"
  },
  "retrieved_context": [],
  "recent_decisions": [],
  "warnings_from_fixed_checks": []
}
```

### 5.2 KB Review Pretext

Use existing retrieval ideas, preferably RRF where available.

Inputs:

- candidate title/content
- top K published group KB items by title/content similarity
- same folder siblings if `folder_id` exists
- recent decisions matching candidate topic
- any fixed-check conflicts already found

Suggested K:

- `kb_items`: 8
- `decisions`: 5
- `folder_siblings`: 5

Each KB item:

```json
{
  "ref": "kb:<id>",
  "title": "...",
  "excerpt": "...",
  "status": "published",
  "scope": "group",
  "source": "manual|llm|upload|ingest",
  "updated_at": "...",
  "folder_id": "...",
  "edges": []
}
```

Each decision:

```json
{
  "ref": "decision:<id>",
  "headline": "...",
  "rationale": "...",
  "apply_outcome": "ok|advisory|partial|failed",
  "created_at": "...",
  "scope_stream_id": "..."
}
```

### 5.3 Task Review Pretext

Inputs:

- candidate title/description/estimate/assignee role
- active plan tasks matching title/description
- done/cancelled tasks matching title/description
- latest requirement
- relevant deliverables/goals
- dependencies around similar tasks
- recent decisions matching the task topic

Suggested packet:

```json
{
  "candidate": {
    "kind": "task_promote",
    "title": "...",
    "description": "...",
    "estimate_hours": 4,
    "assignee_role": "design"
  },
  "plan_context": {
    "requirement_id": "...",
    "requirement_title": "...",
    "budget_hours": 40,
    "current_estimate_total": 32
  },
  "related_tasks": [
    {
      "ref": "task:<id>",
      "title": "...",
      "description": "...",
      "status": "open|done|cancelled",
      "scope": "plan",
      "assignee_role": "...",
      "estimate_hours": 4
    }
  ],
  "recent_decisions": []
}
```

Task-specific semantic questions:

- Is this a duplicate of existing active work?
- Does this reopen completed/cancelled work?
- Does it contradict a recent decision?
- Does it expand scope after a scope cut?
- Does it depend on an unresolved decision?

### 5.4 Decision Review Pretext

Inputs:

- proposed decision title/rationale/source
- prior decisions by semantic similarity
- related KB items
- open dissent rows if any
- tasks/risks touched by proposed apply actions

Decision-specific semantic questions:

- Is this superseding a prior decision?
- Does it contradict a prior decision without saying so?
- Does it lack rationale for a load-bearing change?
- Should this be `request_review` because no explicit supersede relation exists?

## 6. Prompt Contract

The Membrane Agent prompt must say:

- You are reviewing whether a candidate may enter shared team memory.
- Do not rewrite the candidate.
- Do not decide project truth.
- Return JSON only.
- Prefer `request_review` when shared memory may become inconsistent.
- Prefer `request_clarification` when proposer intent is ambiguous.
- Use `reject` only for unsafe, empty, irrelevant, malicious, or clearly invalid candidates.
- Use `auto_merge` only when the candidate is compatible with retrieved context or no relevant context exists.
- Cite conflicts by `ref`.

Schema:

```json
{
  "action": "auto_merge|request_review|request_clarification|reject",
  "reason": "short_machine_reason",
  "diff_summary": "human-readable one paragraph or null",
  "clarify_question": "one focused question or null",
  "conflict_with": ["kb:<id>", "decision:<id>", "task:<id>"],
  "warnings": ["..."],
  "confidence": 0.0
}
```

Validation rules:

- `confidence` in `[0, 1]`
- `conflict_with` refs must exist in pretext
- `request_clarification` must include `clarify_question`
- `request_review` should include `diff_summary`
- invalid output falls back to `request_review`, not `auto_merge`

## 7. Service Integration

Add a Membrane Agent semantic review method, but keep the name simple.

Possible service shape:

```python
class MembraneAgentReviewer:
    async def review_candidate(self, packet: dict) -> MembraneAgentReview:
        ...
```

But product-facing concept remains **Membrane Agent**.

Integration order inside `MembraneService.review(...)`:

```text
1. fixed hard rejects
2. fixed high-confidence blocks
3. build semantic pretext
4. call Membrane Agent
5. validate output
6. combine fixed warnings + agent warnings
7. return MembraneReview
```

Do not call the LLM when:

- candidate has empty/invalid title and caller already validates
- fixed rule already returns `request_clarification`
- fixed rule already returns `request_review` with high confidence and no extra context is needed
- no retrieval service is wired and candidate kind is low risk

Call the LLM when:

- KB candidate is headed for `auto_merge`
- task candidate is headed for `auto_merge` but has enough description/title to retrieve context
- decision candidate would otherwise be advisory-only

## 8. Existing Pollution Audit

Add an internal one-shot command/service method:

```text
audit_published_kb_conflicts(project_id)
```

It should:

- scan `group + published` KB rows
- use deterministic numeric conflict first
- optionally use Membrane Agent pair/cluster review for likely related rows
- output conflict candidates
- either create `IMSuggestion(kind="membrane_review")` or return a report for manual demotion

Do not auto-demote published rows in v1. Existing published memory should be cleaned by owner action.

## 9. Slice Plan

### Slice M1: KB Semantic Review

- Add Membrane Agent structured review class/prompt.
- Add KB pretext builder using candidate + retrieved group KB + recent decisions.
- Wire only `kb_item_group`.
- Keep deterministic checks first.
- Add tests:
  - non-numeric contradiction -> `request_review`
  - elaboration compatible -> `auto_merge`
  - ambiguous supersede/elaborate -> `request_clarification`
  - invalid agent output -> `request_review`
  - `draft` rows remain excluded from retrieval

### Slice M2: Existing KB Audit

- Add audit function/CLI/test endpoint if needed.
- Produce report or IMSuggestions.
- Do not auto-demote.

### Slice M3: Task Semantic Review

- Add task pretext builder.
- Wire `task_promote`.
- Change some current warnings to blocks when the agent detects contradiction with decisions or duplicate active work.
- Add tests:
  - semantic duplicate title mismatch -> `request_review`
  - task contradicts decision -> `request_review`
  - task reopens done work intentionally stated -> warning or review depending confidence

### Slice M4: Decision Semantic Advisory/Block

- Add decision pretext builder.
- Keep human-reviewed paths mostly advisory first.
- Require `request_review` only for clear contradiction without supersede metadata.

### Slice M5: Room/Project Governance

- Wire `manual_room`.
- Room creation pretext includes existing rooms and requested membership.
- Block duplicate room purpose or membership leakage.

## 10. Non-Goals

- Do not make LLM write rows.
- Do not replace deterministic checks.
- Do not scan full project context in prompt.
- Do not auto-delete or auto-demote existing published rows.
- Do not widen UI actions before backend semantics are stable.

## 11. Success Criteria

Membrane is working when:

- a semantic conflict does not become `group + published` without review
- agent pretext only includes published memory that survived the boundary
- owners see a legible diff explaining why review is needed
- proposer gets clarification when intent is ambiguous
- invalid LLM output fails closed
- every shared-state write path can answer: "what membrane review did this pass?"

