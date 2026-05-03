# Design System — WorkGraph

Opinionated visual + motion system for the final-round competition pass. Every choice here has a reason. Deviation requires explicit user approval.

---

## Product Context

- **What this is:** AI-native operating graph for a team. Humans are nodes, sub-agents metabolize signals on edges, the graph is the shared nervous system. Decisions crystallize as first-class nodes with lineage.
- **Who it's for:** 10–30-person knowledge-dense teams — indie game studios, early startups, creative agencies, research groups.
- **Space / industry:** AI-native collaboration. Competing against Slack, Lark, Feishu, Notion, DingTalk, Wukong. All visually interchangeable. Our lane: *group-as-subject* rather than individual-copilot.
- **Project type:** Chat-centered web app with graph-audit surfaces + rendered artifacts. Desktop-first. Bilingual zh + en.

---

## Aesthetic Direction

- **Direction:** *Cool-clinical / blueprint paper.* Clean blue-on-white, structured grid undertones, generous whitespace. The graph is a precise instrument; the chrome around it should read as the same family — engineered, scannable, deliberately calm. (v2, 2026-04-26 — see Decisions Log for the shift from v1 warm-industrial.)
- **Decoration level:** **Intentional.** Subtle blueprint-grid texture on surfaces (~5% opacity, 36px grid + 72px anchor dots). Soft blue radial accents on hero surfaces. Hand-weighted line icons. Ambient motion on organism-level events. Never decorative blobs, never purple gradients, never centered-everything-in-a-grid-of-three.
- **Mood:** Crisp and observant. The product should feel like a clean instrument panel — readable at a glance, structured by intent, paying attention even when idle. The graph breathes; the chrome doesn't fight it.
- **Category break:** Everyone else is cold enterprise chrome with no opinion (Slack), literary minimal (Notion), or AI-purple-soup (every 2025 launch). We're a blueprint instrument: blue, but not generic-SaaS blue — paired with serif display headlines, mono data, and graph-paper backgrounds that signal "this is a structured workspace, not a feed." Remembered within 2 seconds.

---

## Typography

Loaded via Bunny Fonts CDN (no Google telemetry) or self-hosted from `apps/web/public/fonts`.

- **Display / Hero:** `Instrument Serif`, weights 400 + 400 italic.
  - *Why:* Everyone in the category uses Inter / sans. A serif at hero scale signals "thoughtful instrument," not "messaging app." This is the biggest single taste lever.
  - *Where:* H1 on landing + marketing pages, empty-state headlines, book-render section titles, node-detail primary title. Never at body scale.
- **Body / UI:** `General Sans`, weights 400 + 500 + 600.
  - *Why:* Already in the repo, already working, distinct from Inter while remaining scannable. Keep it.
  - *Where:* All body copy, buttons, form inputs, card contents.
- **Mono / data / eyebrows:** `JetBrains Mono`, weights 400 + 500, with `font-feature-settings: "tnum"` for tables.
  - *Why:* Already in. Provides tabular numerals for the perf panel + counts throughout. Signals "this is a real instrument."
  - *Where:* Timestamps, node IDs, perf columns, code in KB items, section eyebrows (11px uppercase caps), citation chips.

**Type scale (tokens, use these — no inline sizes):**

```
--wg-fs-hero:    48px  /  3rem      (serif display only)
--wg-fs-h1:      32px  /  2rem       (serif or sans)
--wg-fs-h2:      18px  /  1.125rem
--wg-fs-h3:      14px  /  0.875rem
--wg-fs-body:    13px  /  0.8125rem
--wg-fs-label:   12px  /  0.75rem
--wg-fs-caption: 11px  /  0.6875rem  (mono, caps, tracking 0.06em)
--wg-lh-tight:   1.25
--wg-lh-normal:  1.5
--wg-lh-display: 1.1
```

---

## Color

All surfaces, text, accents reference variables. No inline hex outside `globals.css` (and this doc).

### Light mode (default — v2 blue/white)

```
--wg-paper:         #f5f8ff   /* page background — pale blueprint */
--wg-surface:       #ffffff   /* card surface */
--wg-surface-raised:#ffffff
--wg-surface-sunk:  #f3f7ff   /* subtle sunk surface — nav rails */

--wg-ink:           #172033   /* deep navy — readable, not pure black */
--wg-ink-soft:      #667085
--wg-ink-faint:     #9aa8bd
--wg-line:          #d9e3f4   /* cool blue-gray hairlines */
--wg-line-soft:     #eef3fb

--wg-accent:        #2563eb   /* blue — crystallization / primary */
--wg-accent-soft:   rgba(37,99,235,0.08)
--wg-accent-ring:   rgba(37,99,235,0.24)

--wg-amber:         #d97706   /* escalation / medium severity / clarifier */
--wg-amber-soft:    rgba(217,119,6,0.10)

--wg-ok:            #16a34a   /* clean green — supported / healthy */
--wg-ok-soft:       rgba(22,163,74,0.10)

--wg-danger:        #dc2626   /* reserved; use sparingly */
```

**Surface texture** (token `--wg-paper-grain`): blueprint grid + anchor dots, ~5% opacity blue lines, 72px tile. Applied via `background-image` on `body`. The grid is the structural metaphor — the chrome reads as the same surface as the graph, not as a separate "container" wrapping it.

### Dark mode (full redesign — not inversion — v2)

```
--wg-paper:         #0b1224   /* night blueprint */
--wg-surface:       #111a2e
--wg-surface-raised:#16213a
--wg-surface-sunk:  #0a1020

--wg-ink:           #e6ecf7
--wg-ink-soft:      #a3afc4
--wg-ink-faint:     #6d7a8f
--wg-line:          #1e2a44
--wg-line-soft:     #182039

--wg-accent:        #3b82f6   /* brighter blue for dark surfaces */
--wg-accent-soft:   rgba(59,130,246,0.18)
--wg-accent-ring:   rgba(59,130,246,0.35)

--wg-amber:         #f59e0b
--wg-amber-soft:    rgba(245,158,11,0.18)

--wg-ok:            #22c55e
--wg-ok-soft:       rgba(34,197,94,0.18)

--wg-danger:        #ef4444
```

Dark-mode grid stays but at lower opacity. Every component must be authored with both modes in mind, not inversion-tested.

### Semantic usage (never break these)

- **Blue (`--wg-accent`)** = a decision moment, a crystallized fact, a primary affordance, a routing target. Used *sparingly* — scarcity is the product's accent. (v1 used terracotta for this slot — same semantic role, different colour.)
- **Amber** = something needs attention / clarification. Escalation, drift alerts, clarifier turns, medium-severity risks.
- **Green (`--wg-ok`)** = confirmed / supported / healthy / "ok" state. Dissent `supported`, member online, commitment on-track.
- **Ink-faint** = ambient / uncited / passive. Uncited claims, read messages, observer-tier restricted placeholders.

---

## Spacing

- **Base unit:** 4px.
- **Scale:** `--wg-space-1 4px · -2 8px · -3 12px · -4 16px · -5 24px · -6 32px · -7 48px · -8 64px · -9 96px`
- **Density:** Comfortable. Stream message card padding **14px** (up from 10px — kills the "stream is 2x denser than rest of app" audit finding). Status / perf / profile cards stay at 16–20px. Difference is intentional: stream optimizes for information flow, dashboards for breathing.

---

## Layout

- **App shell:** Fixed left sidebar 240px (collapsible to 60px at <960px). Main pane fluid to 1280px max. Right rail optional for routed-inbox.
- **Stream (primary surface):** Single column max-width 820px centered. User messages right-aligned 70% max-width, agent turns flowing left-flat. **No cards for agent turns — only for structural events** (⚡ decision, drift, scrimmage result, silent-consensus proposal, routed-inbound).
- **Audit views (`/detail/*`):** Grid-disciplined, dense, minimum chrome.
- **Landing page:** Creative-editorial. Hero uses serif display at 40px. Asymmetric grid. This is the "first 3 seconds" surface.
- **Border radius scale:** `sm: 12px · md: 18px · lg: 26px · full: 9999px`. No uniform-bubble radius everywhere — chip 12px, card 18px, hero/modal 26px, avatar full. Variation signals hierarchy. Bumped 2026-04-27 from the prior 4/6/12 scale to align with the html2 sidebar-first prototype: softer corners read as "blueprint paper" rather than "Material slab."

---

## Motion

Motion is how the organism thesis goes from metaphor to visceral. Five moments are load-bearing; the rest is restraint.

**Easing + duration tokens:**

```
--wg-ease-enter: cubic-bezier(0.2, 0.8, 0.2, 1)
--wg-ease-exit:  cubic-bezier(0.4, 0, 1, 1)
--wg-ease-move:  cubic-bezier(0.4, 0, 0.2, 1)
--wg-dur-micro:  80ms
--wg-dur-short:  180ms
--wg-dur-medium: 320ms
--wg-dur-long:   560ms
```

### The 5 load-bearing moments

1. **⚡ Decision crystallization.** When a `DecisionRow` lands in-stream: blue (`--wg-accent`) ring pulse (320ms), card scale from 0.97 → 1.0, accompanying graph-view node drop-in if graph is visible. Once per decision, never on replays.
2. **Drift alert emergence.** Don't pop from corner. Float up from the affected node with a subtle shadow expansion. Feels like the organism noticing.
3. **Citation chip activation.** When the edge LLM emits a cited claim, each chip does a brief amber glow (180ms) as the text types in, then settles to neutral. Evidence lighting up in sequence.
4. **Scrimmage running card.** Two small glyphs (filled circle + empty circle) rotating around a central axis while agents debate. Stops on convergence with a soft click-in of the proposal card.
5. **Silent-consensus proposal assembly.** Member avatars converge from their positions in the graph into a cluster above the proposal text. Stagger 60ms per avatar. Confirms the behavioral-agreement thesis visually.

### Restraint rules

- Never animate primary text size/position after mount.
- `prefers-reduced-motion: reduce` respected everywhere — drops to opacity-only fades.
- No scroll-triggered animations except the ambient organism pulse (see below).
- Page transitions are instant. No spinner-between-routes theatre.

### Ambient "breathing" pulse (optional, feature-flag)

Tiny indicator (8px dot) in the sidebar footer that pulses at ~60 BPM (1000ms cycle). Only when WS connected. Off on `prefers-reduced-motion`. Taste call: decide during final polish whether this is magic or kitsch.

---

## Iconography

- **Library:** `lucide-react`. Not Phosphor, not Feather, not Heroicons.
- **Stroke width:** 1.5 (not the default 2). Thinner strokes feel hand-drawn, organism-adjacent.
- **Size scale:** 14px (inline), 16px (button), 20px (nav), 24px (hero). No other sizes.
- **Color:** `currentColor` always. Icons inherit from context, never declare their own hue.
- **Critical icons keep a consistent role:**
  - ⚡ (built-in glyph, not lucide) — decision crystallization, only
  - 🤖 — edge agent (one robot in the chip, not decorative — the agent's voice, not its brand)
  - ❓ — clarifier sub-agent turn
  - ⚖ — conflict / scrimmage
  - ⚠ — escalation / drift / amber states

Never use emoji outside these five signal roles.

---

## Components (the floor)

Every primary-route component must use the `apps/web/src/components/ui/` primitives. Inline `style=` is a code-smell — flag in review.

- `<Button>` — variant: `primary | ghost | amber | danger | link`. Size: `sm | md`. No other buttons.
- `<Card>` — variant: `default | raised | sunk`. Accent: `accent | amber | ok | null` (the `accent` slot is now blue per v2; the prop name `accent` survived the v1→v2 rename). Never hand-rolled borders.
- `<Heading>` — level `1 | 2 | 3`. Uses `--wg-fs-h1/2/3`. Serif variant for level 1 on landing + node detail.
- `<Text>` — variant: `body | label | caption | mono`. Muted boolean.
- `<EmptyState>` — dashed border, centered muted text + optional CTA. Consistent across every empty list.
- `<CitedClaimList>` — chips with deep-link to `/projects/[id]/nodes/[nodeId]`. Uncited claims render `--wg-ink-faint` italic.

---

## Copy voice

- **Tone:** Instrument, not butler. "Drift detected on Stellar Drift" beats "Oops! We noticed something." No emoji in copy outside the signal-role set above.
- **Button labels:** Verb + noun ("Accept decision", "Record dissent", "Publish to project"). Never bare verbs ("Submit").
- **Empty states:** Teach the product's shape. "No decisions yet — ask your edge agent something worth crystallizing." Every empty state is a micro-tutorial.
- **Error states:** Name what happened + what the organism is doing about it. "Can't reach DeepSeek — retrying every 30s" beats "Something went wrong."

---

## Decisions Log

| Date       | Decision                                              | Rationale                                                                 |
|------------|-------------------------------------------------------|---------------------------------------------------------------------------|
| 2026-04-22 | Initial design system created                         | Final-round competition polish. Established warm-industrial + bio undertones. |
| 2026-04-22 | Instrument Serif for display                          | Category-break taste lever. Everyone else uses Inter. We use a serif.       |
| 2026-04-22 | Keep General Sans + JetBrains Mono                    | Already working, already in repo. Only replace display.                     |
| 2026-04-22 | Warmer neutrals (`#0f0e0d`/`#f7f2e8`)                  | Reinforces lab-notebook vs. sterile enterprise.                             |
| 2026-04-22 | 5 load-bearing motion moments, rest restrained        | Motion is how "organism" stops being metaphor. Scarcity keeps them magic.   |
| 2026-04-22 | Dark mode = full redesign, not inversion              | Prod demo URL will be visited on both modes. Inversion always looks cheap. |
| 2026-04-22 | Icon stroke 1.5 on lucide                             | Thinner strokes feel hand-drawn, match biological undertones.               |
| 2026-04-26 | **v2 — switch palette to blue/white (cool-clinical)** | Per user direction. v1 warm-industrial was a deliberate category-break, but the user wants the product to read as a clean collaboration instrument rather than a literary lab notebook. Token NAMES unchanged in `globals.css` (so component code is untouched) — only HEX values shifted. Surface texture moves from noise grain to blueprint grid: same "structured surface" intent, on-theme for the graph instrument. v1 palette preserved in git history if we ever need to compare. Type stack (Instrument Serif / General Sans / JetBrains Mono) unchanged — the serif headline is still the highest-leverage taste lever and pairs well with cool blues. |
| 2026-04-26 | **v2 — keep Instrument Serif over Georgia**            | The reference HTML uses Georgia, but Instrument Serif is the genuine differentiator vs. category defaults. Switching to Georgia would weaken the "thoughtful instrument" signal for no gain. |
| 2026-04-26 | **v2 — surface texture = blueprint grid, not noise**   | Noise grain was for the lab-notebook mood. Blueprint grid signals "this surface is structured, this is where the graph lives." Same a11y profile (static SVG, mask-faded). |

---

## What's next (implementation priorities — not this doc's job to dictate)

1. Add the new tokens to `apps/web/src/app/globals.css`.
2. Wire Instrument Serif via Bunny Fonts in `apps/web/src/app/layout.tsx`.
3. Build the 5 motion moments in order of demo visibility: **decision crystallization → citation activation → drift emergence → scrimmage running → silent-consensus assembly**.
4. Dark mode sweep across the 5 primary routes.
5. QA pass via `/design-review` once the above lands.

All of the above is out of scope for this DESIGN.md — it defines the spec; implementation is separate work.
