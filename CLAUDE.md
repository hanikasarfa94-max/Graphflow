# CLAUDE.md — project conventions for AI agents

Read `docs/north-star.md` before any product-shaping work. Read `docs/architecture.md` for the visual summary of what the system is.

## Design System

**Always read `DESIGN.md` before making any visual or UI decisions.** All font choices, colors, spacing, and aesthetic direction are defined there. Do not deviate without explicit user approval.

- Inline `style={{}}` blocks are a code-smell — prefer the `<Button> / <Card> / <Heading> / <Text> / <EmptyState>` primitives in `apps/web/src/components/ui/`.
- Hex literals outside `globals.css` and `DESIGN.md` are not allowed. Reference CSS variables.
- Motion is load-bearing for 5 specific moments (see `DESIGN.md §Motion`). Everywhere else: restraint.
- `prefers-reduced-motion: reduce` respected everywhere.
- Dark mode is a full redesign, not an inversion. Author every component with both modes in mind.
- In QA / code review: flag any code that doesn't match `DESIGN.md`.

## Plans

- `PLAN-v3.md` and `PLAN-v4.md` — completed build plans, historical record.
- `docs/north-star.md` — current product intent.
- `docs/architecture.md` — current-state visual summary, image-gen friendly.
- `docs/competition.zh-CN.md` — ByteDance competition submission (final-round ready).

## Archived docs (do not read as current spec)

- `docs/dev.md`, `docs/eng_backlog.md`, `docs/prompt-contracts.md`, `docs/resume.md`, `docs/signal-chain-plan.md`
- `PLAN.md`, `PLAN-v2.md`
- `AGENT.md`

All carry archive banners. Treat as historical.
