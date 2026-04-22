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

- **Direction:** *Warm-industrial with biological undertones.* Blueprint paper meets lab notebook meets the sage-green of old CRT displays. The graph is a living instrument.
- **Decoration level:** **Intentional.** Subtle paper-grain texture (~3% opacity) on surfaces. Hand-weighted line icons. Ambient motion on organism-level events. Never decorative blobs, never purple gradients, never centered-everything-in-a-grid-of-three.
- **Mood:** Alive and observant. The product should feel like it's paying attention even when idle. The graph breathes.
- **Category break:** Everyone else is cold enterprise chrome (Slack) or literary minimal (Notion). We're warm-industrial. Remembered within 2 seconds.

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
--wg-fs-hero:    40px  /  2.5rem   (serif display only)
--wg-fs-h1:      28px  /  1.75rem  (serif or sans)
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

Evolve the existing token system. All surfaces, text, accents reference variables. No inline hex.

### Light mode (default)

```
--wg-paper:         #f7f2e8   /* was #fafaf7 — warmer, lab-notebook */
--wg-surface:       #fbf7ed
--wg-surface-raised:#ffffff
--wg-surface-sunk:  #ede7d6

--wg-ink:           #0f0e0d   /* was #1a1a1a — warmer black */
--wg-ink-soft:      #5a5652
--wg-ink-faint:     #9a958c
--wg-line:          #e6ded0   /* dividers + borders */

--wg-accent:        #c0471e   /* terracotta — crystallization / primary */
--wg-accent-soft:   #f2d9cc
--wg-accent-ring:   rgba(192,71,30,0.18)

--wg-amber:         #b5802b   /* escalation / medium severity / clarifier */
--wg-amber-soft:    #f4e4bf

--wg-ok:            #4d7a4a   /* sage — supported / healthy */
--wg-ok-soft:       #d8e4d5

--wg-danger:        #a33131   /* reserved; use sparingly */
```

**Paper grain** (optional overlay, ~3% opacity, tiled 256px SVG noise): `url(data:image/svg+xml;…)` applied as `background-image` on `body` + `[data-surface="raised"]`. Additive, a11y-neutral, mobile-OK.

### Dark mode (full redesign — not inversion)

```
--wg-paper:         #0f0e0d
--wg-surface:       #171513
--wg-surface-raised:#1f1c19
--wg-surface-sunk:  #0a0907

--wg-ink:           #f7f2e8
--wg-ink-soft:      #b8b0a3
--wg-ink-faint:     #6f6860
--wg-line:          #2a2622

--wg-accent:        #d85c33   /* +8% saturation for dark surfaces */
--wg-accent-soft:   rgba(216,92,51,0.18)
--wg-accent-ring:   rgba(216,92,51,0.35)

--wg-amber:         #d09a3c
--wg-amber-soft:    rgba(208,154,60,0.18)

--wg-ok:            #6d9c69
--wg-ok-soft:       rgba(109,156,105,0.18)

--wg-danger:        #c75151
```

Dark mode paper grain stays but at 4% opacity. Every component must be authored with both modes in mind, not inversion-tested.

### Semantic usage (never break these)

- **Terracotta** = a decision moment, a crystallized fact, a primary affordance. Used *sparingly* — scarcity is the product's accent.
- **Amber** = something needs attention / clarification. Escalation, drift alerts, clarifier turns, medium-severity risks.
- **Sage** = confirmed / supported / healthy / "ok" state. Dissent `supported`, member online, commitment on-track.
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
- **Border radius scale:** `sm: 4px · md: 6px · lg: 12px · full: 9999px`. No uniform-bubble radius everywhere — chip 4px, card 6px, modal 12px, avatar full. Variation signals hierarchy.

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

1. **⚡ Decision crystallization.** When a `DecisionRow` lands in-stream: terracotta ring pulse (320ms), card scale from 0.97 → 1.0, accompanying graph-view node drop-in if graph is visible. Once per decision, never on replays.
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
  - 🧠 — edge agent (kept minimal, the brain stays in the chip, not decorative)
  - ❓ — clarifier sub-agent turn
  - ⚖ — conflict / scrimmage
  - ⚠ — escalation / drift / amber states

Never use emoji outside these five signal roles.

---

## Components (the floor)

Every primary-route component must use the `apps/web/src/components/ui/` primitives. Inline `style=` is a code-smell — flag in review.

- `<Button>` — variant: `primary | ghost | amber | danger | link`. Size: `sm | md`. No other buttons.
- `<Card>` — variant: `default | raised | sunk`. Accent: `terracotta | amber | sage | null`. Never hand-rolled borders.
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

---

## What's next (implementation priorities — not this doc's job to dictate)

1. Add the new tokens to `apps/web/src/app/globals.css`.
2. Wire Instrument Serif via Bunny Fonts in `apps/web/src/app/layout.tsx`.
3. Build the 5 motion moments in order of demo visibility: **decision crystallization → citation activation → drift emergence → scrimmage running → silent-consensus assembly**.
4. Dark mode sweep across the 5 primary routes.
5. QA pass via `/design-review` once the above lands.

All of the above is out of scope for this DESIGN.md — it defines the spec; implementation is separate work.
