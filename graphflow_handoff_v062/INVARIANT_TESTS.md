# INVARIANT_TESTS.md

Implement these as CI/contract tests before feature teams build.

## Primary navigation invariant

```ts
expect(primaryNavItems).toEqual([
  "My AI",
  "Conversations",
  "Tasks",
  "Documents / KB",
  "Flow Center"
]);

for (const forbidden of ["Project", "Graph", "Memory", "Capability", "Embedded Views"]) {
  expect(primaryNavItems).not.toContain(forbidden);
}
```

## Create menu invariant

```ts
const menu = await get("/api/create-menu");
expect(menu.items.map(i => i.type)).toEqual(["conversation", "document", "upload", "project_scope"]);
expect(menu.excluded_direct_creations).toEqual(["task", "topic", "flow_request", "memory"]);
```

## AI Assistance no-mutation

```ts
const res = await post("/api/ai-assistance/run", payload);
expect(res.mutates_state).toBe(false);
expect(res.proposal).toBeDefined();
```

## Flow response memory decoupling

```ts
const res = await post("/api/flow-requests/flow_123/respond", payload);
expect(res.memory_candidate_prompt.actions).toEqual(expect.arrayContaining(["review", "skip", "later"]));
expect(res.memory_auto_accepted).not.toBe(true);
```

## Later creates deferred candidate

```ts
const res = await post("/api/memory-candidates/memcand_001/defer", {});
expect(res.status).toBe("deferred");
```

## Skip reversible

```ts
await post("/api/memory-candidates/memcand_001/skip");
const flow = await get("/api/flow-responses/flowresp_001");
expect(flow.available_actions).toContain("generate_memory_candidate");
```

## Authority enforcement

```ts
await expect(
  postAs("project_member", "/api/memory-candidates/memcand_001/accept", payload)
).rejects.toMatchObject({ status: 403, error: "authority_required" });
```

## Memory lineage required

```ts
const res = await postAs("pricing_owner", "/api/memory-candidates/memcand_001/accept", payload);
expect(res.lineage.verbatim_source_id).toBeDefined();
expect(res.lineage.ai_distillation_id).toBeDefined();
expect(res.lineage.accepted_by).toBeDefined();
```

## Compression analysis shape

```ts
const candidate = await get("/api/memory-candidates/memcand_001");
expect(candidate.compression_analysis.caveat).toContain("does not guarantee");
```

## Topic deduplication

```ts
const res = await get("/api/conversations?scope_id=scope_tikhub");
const recentIds = new Set(res.recent.map(c => c.id));
for (const topic of res.active_topics) expect(recentIds.has(topic.id)).toBe(false);
```

## Project not routable as page

```ts
await expect(get("/projects/scope_tikhub")).rejects.toMatchObject({ status: 404 });
const brief = await get("/api/scopes/scope_tikhub/project-brief");
expect(brief.document_id).toBeDefined();
```
