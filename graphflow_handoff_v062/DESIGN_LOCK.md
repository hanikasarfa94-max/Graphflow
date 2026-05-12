# DESIGN_LOCK.md

## Product statement

GraphFlow opens with personal reasoning, preserves natural conversation, structures only the moments where coordination breaks, and turns confirmed outcomes into reusable team state.

## Locked IA

Primary surfaces:

```txt
My AI
Conversations
Tasks
Documents / KB
Flow Center
```

System concepts that are not primary pages:

```txt
Project       = scope / membership / permissions / object boundary
Project Brief = pinned KB document
Memory        = accepted organizational knowledge
Graph         = internal relationship substrate
Capability    = routing evidence layer
```

## Hard invariants

1. My AI is default landing route.
2. Project is never a page.
3. Create Menu excludes blank-start Task / Topic / Flow / Memory.
4. AI Assistance must return proposals only.
5. Actions mutate state.
6. Flow acceptance does not auto-accept memory.
7. Memory crystallization is a separate decision.
8. Memory acceptance requires server-side authority.
9. Memory candidates must preserve lineage.
10. Right rail follows shared spine: Context / Related Work / Evidence / AI Assistance / CTA.

## Memory doctrine

AI may propose memory. Authority accepts memory. The Membrane enforces whether acceptance is automatic, delegated, or review-required.

Required lineage:

```txt
verbatim source → AI distillation → reviewer revision if any → accepted memory atom → outbound citations/dependencies
```

## Scope doctrine

Project focus is a mode, not a filter. When active, it affects My AI retrieval, Tasks, Documents / KB, Flow Center, routing suggestions, and memory candidate scope. Always show persistent scope band.
