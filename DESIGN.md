# Design System — GraphFlow v3

Visual + motion system locked 2026-05-12. Paired with `BUILD-v062.md` (build plan) and `graphflow_handoff_v062/DESIGN_LOCK.md` (product doctrine).

**This is a full refresh.** v2 (cool-clinical blueprint) is retired. Every choice below has a reason. Deviation requires explicit user approval; flag in code review.

---

## Product context

GraphFlow is an AI-native operating graph for a team. Five primary surfaces — My AI · Conversations · Tasks · Documents/KB · Flow Center. Project is scope, not page. Memory is what the team accepts as canonical. AI proposes; authority accepts.

The chrome must read as **a calm, trustworthy instrument**. Not a chat app. Not a Notion clone. Not a Slack-with-AI bolt-on. The serif headlines and the lineage-rich surfaces are the visual proof that this is a different kind of tool.

---

## Aesthetic direction

- **Direction:** *Quiet instrument, warm paper, sharp graph.* Cooler than v1 (warm-terracotta), warmer than v2 (cool-clinical blueprint). Surface neutrals drift slightly warm so the product reads as paper-considered rather than enterprise-clinical. Accent geometry is sharper, line weights thinner, shadows lighter. The graph is the precision instrument; the chrome breathes around it.
- **Decoration level:** **Restrained.** No paper grain. No blueprint grid. Surface texture is a single soft radial wash from top-left of the page (~6% accent at 18%, fading to transparent). One wash, not three. Cards sit on the paper like sheets, not like Material slabs.
- **Mood:** Considered, observant, never anxious. The product should feel like a research notebook held by someone who is paying attention.
- **Category break:** Slack is enterprise-chrome. Notion is literary-minimal. Linear is dark-precision. ChatGPT is stark-white-utilitarian. We are **paper-and-accent**: warm paper, serif headlines, blue+violet duo accent, mint confirmations. Read as "thoughtful working surface for serious teams" within 2 seconds.

---

## Typography

Three faces. No Inter. No SF Pro. No Roboto. The display serif is the highest-leverage taste lever and stays.

- **Display / Hero:** `Instrument Serif`, 400 + 400 italic. Bunny Fonts CDN.
  - *Where:* H1 on `/my-ai` landing, empty-state headlines, node-detail primary title, document-view titles, memory-atom titles, marketing surfaces.
  - *Why:* Categorical break. Every competitor uses Inter at hero. A serif at hero scale signals "this is an instrument considered by someone with taste."

- **Body / UI:** `General Sans`, 400 + 500 + 600. Fontshare CDN.
  - *Where:* All body copy, buttons, form inputs, table cells, card content.
  - *Why:* Already in repo, already loved. Cleaner geometry than Inter; ligatures + dlig features make number-heavy tables read better.

- **Mono / data / eyebrows:** `JetBrains Mono`, 400 + 500. Google Fonts CDN.
  - *Where:* Timestamps, IDs (`D-102`, `M-213`), eyebrows (10–11px caps), table numerics, code in KB items, citation chips.
  - Apply `font-feature-settings: "tnum", "zero"` globally on mono so columns align and `0` reads as zero.

**Type scale tokens — single source of truth. Inline sizes are a code-smell.**

```
--wg-fs-display: 56px / 3.5rem      (serif only; one per page)
--wg-fs-hero:    40px / 2.5rem      (serif or sans, H1 on inner pages)
--wg-fs-h1:      28px / 1.75rem
--wg-fs-h2:      20px / 1.25rem
--wg-fs-h3:      16px / 1rem
--wg-fs-body:    14px / 0.875rem    (bumped from 13px — comfortable density)
--wg-fs-label:   13px / 0.8125rem
--wg-fs-caption: 11px / 0.6875rem   (mono, caps, tracking 0.08em)

--wg-lh-display: 1.05
--wg-lh-tight:   1.25
--wg-lh-normal:  1.55
```

---

## Color

All colors via CSS variables. **No hex outside `globals.css` and this doc.** ESLint rule + review flag.

### Light mode

```
--wg-paper:          #F7F6F2   /* slightly warm cool neutral — the "paper" */
--wg-paper-tint:     #FBFAF7   /* gradient top-stop */
--wg-surface:        #FFFFFF
--wg-surface-raised: #FFFFFF
--wg-surface-sunk:   #F1EFEA   /* sunk panels, scope-band, nav rails */

--wg-ink:            #14171F   /* near-black, cool tone */
--wg-ink-soft:       #5A6172
--wg-ink-faint:      #95A0B5   /* uncited, passive, placeholder */
--wg-line:           #E4E2DC   /* hairlines — warm taupe-gray */
--wg-line-soft:      #EFEDE7

/* Primary — Blue. Decision crystallization, primary CTAs, focus rings. */
--wg-accent:         #2864E8
--wg-accent-soft:    rgba(40, 100, 232, 0.08)
--wg-accent-ring:    rgba(40, 100, 232, 0.24)
--wg-accent-hover:   #1F52C7

/* Secondary — Violet. AI Assistance, proposal cards, routing suggestions.
   Semantically distinct from primary blue: blue = canonical / accepted,
   violet = AI-proposed / not-yet-canonical. Never use violet for a
   primary action — proposals are by definition not authoritative. */
--wg-ai:             #6E59E8
--wg-ai-soft:        rgba(110, 89, 232, 0.10)
--wg-ai-ring:        rgba(110, 89, 232, 0.22)

/* Confirmed / supported / healthy. Mint, not pure green. */
--wg-ok:             #1F9D7A
--wg-ok-soft:        rgba(31, 157, 122, 0.10)

/* Review pending, needs attention, drift. Amber, slightly muted from v2. */
--wg-amber:          #D08A1E
--wg-amber-soft:     rgba(208, 138, 30, 0.12)

/* Irreversible only — reject, destroy. Used sparingly. */
--wg-danger:         #C2362B
--wg-danger-soft:    rgba(194, 54, 43, 0.10)
```

### Dark mode (authored independently, not inverted)

```
--wg-paper:          #0D1018
--wg-paper-tint:     #11151F
--wg-surface:        #141823
--wg-surface-raised: #1A1F2D
--wg-surface-sunk:   #0A0D14

--wg-ink:            #ECEEF3
--wg-ink-soft:       #A2A9BA
--wg-ink-faint:      #6A7287
--wg-line:           #1F2533
--wg-line-soft:      #181C28

--wg-accent:         #4F86F3
--wg-accent-soft:    rgba(79, 134, 243, 0.16)
--wg-accent-ring:    rgba(79, 134, 243, 0.32)
--wg-accent-hover:   #6C9BFB

--wg-ai:             #9582F3
--wg-ai-soft:        rgba(149, 130, 243, 0.18)
--wg-ai-ring:        rgba(149, 130, 243, 0.30)

--wg-ok:             #2BBF8E
--wg-ok-soft:        rgba(43, 191, 142, 0.18)

--wg-amber:          #E8A53E
--wg-amber-soft:     rgba(232, 165, 62, 0.20)

--wg-danger:         #E25B4F
--wg-danger-soft:    rgba(226, 91, 79, 0.18)
```

### Semantic rules — never break these

| Token | Meaning | Used in |
|---|---|---|
| `--wg-accent` (blue) | Canonical · accepted · primary action · focus | Decision crystallizations, primary buttons, focus rings, the "accepted memory" pill |
| `--wg-ai` (violet) | AI-proposed · pre-canonical · routing | Proposal cards, AI Assistance buttons, route-suggestion chips, draft memory atoms |
| `--wg-ok` (mint) | Confirmed · supported · healthy | Online presence, on-track commitments, "accepted" state on a candidate after the action |
| `--wg-amber` | Review pending · drift · needs attention | Review-pending memory candidates, drift cards, clarification turns |
| `--wg-danger` | Irreversible · reject · destroy | Reject candidate, delete document, archive memory |
| `--wg-ink-faint` | Ambient · uncited · passive | Uncited claims, read messages, observer-scope placeholders |

**Scarcity is the product's accent.** Primary blue on screen ≤ 5% of pixels at any time. Two violet pills per surface max. Mint only on confirmed states. Amber draws the eye — use when the eye is actually wanted.

---

## Spacing

4px base. Scale unchanged from v2.

```
--wg-s-1: 4px   · --wg-s-2: 8px   · --wg-s-3: 12px  · --wg-s-4: 16px
--wg-s-5: 24px  · --wg-s-6: 32px  · --wg-s-7: 48px  · --wg-s-8: 64px
--wg-s-9: 96px
```

Density rules:
- **Conversations + stream surfaces:** comfortable. Card padding 16px, message gap 12px.
- **Tasks / Flow Center tables:** dense. Row padding 12px vertical, 14px horizontal.
- **My AI landing + Documents:** generous. Section gap 32px+, hero margin-top 48px.
- **Right rail:** dense but breathable. Section padding 14px.

---

## Layout

- **App shell:** Sidebar fixed 240px (collapsible 64px at < 1100px). Topbar 56px. Scope band 40px when active. Main pane fluid to 1320px max-width centered.
- **Right rail:** 360px optional. Drag-resizable between 320–480px. Persists per surface.
- **Drawer host:** right-side overlay drawer, 520px default, opens above main pane with backdrop scrim at 30% black.
- **Hero / landing:** asymmetric grid, max-width 920px centered, generous side padding 96px+.

### Border radius (bumped from v2)

```
--wg-radius-xs:   8px    /* chips, tags, badges */
--wg-radius-sm:   12px   /* buttons, inputs, small cards */
--wg-radius-md:   16px   /* cards, panels */
--wg-radius-lg:   20px   /* primary cards, drawer panels */
--wg-radius-xl:   28px   /* hero cards, modals */
--wg-radius-full: 9999px /* avatars, pills, kbd */
```

### Elevation

Light shadows, accent-tinted on light mode (the cool tint reads as "considered" rather than "lifted"). Dark mode uses neutral shadows so the surface depth reads without competing with the accent rings.

```
--wg-shadow-xs:  0 1px 2px   rgba(20, 23, 31, 0.04)
--wg-shadow-sm:  0 4px 12px  rgba(40, 100, 232, 0.06)
--wg-shadow:     0 8px 24px  rgba(40, 100, 232, 0.08)
--wg-shadow-lg:  0 16px 48px rgba(40, 100, 232, 0.10)
--wg-shadow-xl:  0 24px 72px rgba(40, 100, 232, 0.12)
```

Cards default to `--wg-shadow-sm`. Drawer + modal use `--wg-shadow-lg`. Hover transitions shadow up one step, never `transform: translateY`.

---

## Motion

Five load-bearing moments wired to v0.6.2 surfaces. The rest is restraint. `prefers-reduced-motion: reduce` respected everywhere — drops to opacity-only.

### Tokens

```
--wg-ease-enter: cubic-bezier(0.2, 0.8, 0.2, 1)
--wg-ease-exit:  cubic-bezier(0.4, 0, 1, 1)
--wg-ease-move:  cubic-bezier(0.4, 0, 0.2, 1)
--wg-ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1)

--wg-dur-micro:  80ms     /* hover, focus */
--wg-dur-short:  180ms    /* button press, tooltip */
--wg-dur-medium: 320ms    /* card enter, drawer open */
--wg-dur-long:   560ms    /* decision crystallization */
```

### The 5 load-bearing moments

1. **⚡ Decision crystallization (memory accepted, decision crystallized).** Blue ring pulse from card edge, 560ms, plus a brief Instrument-Serif italic eyebrow that fades in `accepted` over 320ms. Once. Never on replay.

2. **🧬 Memory acceptance.** When a candidate moves `review_pending → accepted` in `MemoryReviewDrawer`: the proposed atom card scales from 0.97 → 1.0, mint ring sweeps once around the perimeter, lineage timeline reveals the new node with a 180ms stagger per lineage step.

3. **✈ Flow request sent.** When a flow_request goes draft → sent: the drawer's primary action glides the card title left 24px, fades opacity to 0 over 240ms, drawer auto-dismisses 80ms after.

4. **🪟 Right rail content reveal.** When a primary object loads, right-rail sections fade-up 8px with 60ms stagger between Context → Related Work → Evidence → AI Assistance → Primary Action. Total: 600ms. Skipped on `prefers-reduced-motion`.

5. **🎚 Drawer enter.** Drawer slides in from right 24px + 0 → 1 opacity, 320ms, spring easing. Backdrop scrim fades 0 → 0.30, 180ms. Closing reverses in 220ms with exit easing.

### Restraint rules

- No scroll-triggered animations. Period.
- No spinner-between-routes. Page transitions are instant; skeleton loaders only inside content.
- No bouncing arrows, no pulsing CTAs except the decision-crystallization moment.
- Never animate primary text size or position after mount. Layout shift is a bug.
- Never animate `transform` on React Flow nodes — RF sets inline `transform: translate(...)` for positioning; animating it pins every node to the same origin. Use `box-shadow` for hover/active states on graph nodes. (Preserved from v2 hard-won lesson.)

### Ambient pulse — removed

The v2 sidebar-footer breathing pulse is **out**. Taste call: when the chrome is restrained and the graph is rich, the ambient pulse competes for attention rather than ground it.

---

## Iconography

- **Library:** `lucide-react`. Not Phosphor, not Feather.
- **Stroke width:** 1.5 globally. Thinner than default 2; reads as "hand-drawn instrument" rather than "icon font."
- **Sizes:** 14 (inline) · 16 (button) · 18 (nav) · 20 (section heading) · 24 (hero icon, rare).
- **Color:** `currentColor` always. Icons inherit; no hue declared on the icon itself.

Reserved glyphs (use only for the listed role; never decoratively):

| Glyph | Role |
|---|---|
| ⚡ | Decision crystallization (built-in glyph, not lucide — needs to stand apart) |
| 🧬 | Memory atom acceptance (one place: the crystallized-memory line in MemoryReviewDrawer) |
| 🤖 | Edge sub-agent voice attribution |
| ❓ | Clarifier sub-agent turn |
| ⚖ | Conflict / scrimmage result |
| ⚠ | Drift / escalation / amber states |

No other emoji in copy. ESLint rule.

---

## Components — the floor

All primary-route components must use primitives in `apps/web/src/components/ui/`. Inline `style={{}}` is a code-smell; flag in review.

- `<Button>` — variants: `primary | secondary | ai | ghost | amber | danger | link`. Sizes: `sm | md | lg`. `ai` variant uses `--wg-ai` for the AI-Assistance-buttons-return-proposals-only rule.
- `<Card>` — variants: `default | raised | sunk`. Accent prop: `accent | ai | ok | amber | danger | null`. Header / body / footer slots.
- `<Heading>` — levels 1–3. `serif` boolean for the display face (default true on level 1).
- `<Text>` — variants: `body | label | caption | mono`. `muted` boolean.
- `<EmptyState>` — centered illustration + serif headline + muted subtitle + optional CTA. Consistent across every empty list.
- `<Pill>` — tones from the semantic table above (`accent | ai | ok | amber | danger | slate`). Pills carry meaning; do not use as decoration.
- `<CitedClaim>` — chip with deep-link to `/nodes/[id]` etc. (post Phase E URL migration). Uncited claims render `--wg-ink-faint` italic.
- `<AuthorityBadge>` — renders from server `authority_check`. Never infers from local role strings.
- `<CompressionWarning>` — yellow-bordered panel inside MemoryReviewDrawer. Must render the `caveat` string verbatim from server.
- `<LineageTimeline>` — vertical timeline: verbatim → distillation → revision → accepted, with relative-time stamps in mono.

---

## Copy voice

- **Tone:** Instrument, not butler. *"Drift detected on Stellar Drift"* beats *"Oops! We noticed something."*
- **Button labels:** Verb + object. *"Accept memory"*, *"Send flow request"*, *"Crystallize decision"*. Never bare verbs (*"Submit"*, *"Save"*).
- **Empty states:** Teach the product's shape. *"No memories yet. AI will propose them as your team works — you'll decide what becomes canonical."* Each empty state is a micro-tutorial.
- **Error states:** Name what happened + what the organism is doing. *"Can't reach DeepSeek — retrying in 30s"* beats *"Something went wrong."*
- **Authority failures:** Direct. *"You don't have authority to accept this memory. Request review from a pricing owner."* — never hide the constraint.

---

## Bilingual zh + en

Every string ships through `next-intl`. Doctrine strings require careful translation — these phrases carry the product's argument and a sloppy translation breaks the thesis. Reviewed before merge:

- "Memory crystallization is a separate decision." / 「记忆固化是一次独立的判断。」
- "AI Assistance creates proposals only." / 「AI 辅助仅生成提议。」
- "Project is scope, not page." / 「项目是范围，不是页面。」
- "Only blank-start objects live in Create." / 「创建菜单只接收无锚点对象。」
- "No warning does not guarantee faithful distillation." / 「没有警告不代表蒸馏完全准确。」

---

## Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-12 | **v3 full refresh** — palette + typography + motion all retired from v2 | Competition over; user direction is "finally beautiful." v2's cool-clinical austerity left no warmth; the product needs to feel considered, not antiseptic. |
| 2026-05-12 | **Two-accent palette (blue + violet)** | Blue = canonical, violet = AI-proposed. The proposal/action split in v0.6.2's API contract is the product's most load-bearing distinction; the palette must carry it. v2's single-blue collapsed both into one signal. |
| 2026-05-12 | **Warmer paper (#F7F6F2)** | v2's `#F5F8FF` read as enterprise-clinical. Drift slightly warm — paper, not screen. |
| 2026-05-12 | **Drop paper grain + blueprint grid** | v2's grid was too literal: "look, it's a graph product, here's a grid." The graph itself is the metaphor; the chrome around it should not also be the metaphor. Single radial wash replaces all texture. |
| 2026-05-12 | **Larger radii (12/16/20/28 from 12/18/26)** | v0.6.2 prototype reads as paper-blueprint with softer corners; aligns. |
| 2026-05-12 | **Keep Instrument Serif** | Highest-leverage taste lever. Every competitor's H1 is Inter. Don't blink. |
| 2026-05-12 | **Keep General Sans body** | Already loaded, working, distinct. The display face is the differentiator. |
| 2026-05-12 | **Ambient pulse removed** | Compete for attention with the graph itself, not the sidebar. |
| 2026-05-12 | **5 motion moments rebound to v0.6.2 surfaces** | v2's moments (scrimmage glyphs, silent-consensus assembly) targeted features that aren't primary in the v0.6.2 surface set. New moments hit the surfaces users actually live in: memory acceptance, flow send, right rail reveal, drawer enter, decision crystallization. |

---

## What's next (out of scope for this doc)

1. Apply tokens to `apps/web/src/app/globals.css` (Phase A.3 of `BUILD-v062.md`)
2. Wire Instrument Serif via Bunny Fonts in `layout.tsx`
3. Update `<Card>`, `<Button>`, `<Pill>`, `<Heading>` primitives with new variants
4. Build the 5 motion moments — order of demo visibility: decision crystallize → memory accept → flow send → drawer enter → right rail reveal
5. Dark mode QA pass across the 5 primary surfaces
6. `/design-review` pass after Phase A lands
