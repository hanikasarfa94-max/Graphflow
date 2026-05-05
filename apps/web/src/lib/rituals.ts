// Rituals — productized GraphFlow workflows surfaced as slash commands.
//
// Picking the slash command in the Composer expands to a templated
// natural-language message; the existing Edge agent then routes it to
// the right skill via its prompt (the `propose_wiki_entry` /
// `routing_suggest` / `risk_scan` / `why_chain` family). No new BE
// surface yet — this is a UX layer on top of the skill dispatch the
// agent already does.
//
// Two no-skill rituals (`handoff`, `crystallize`) point to existing
// dedicated UI flows; for those we keep the slash command as a
// templated send for now and follow up with a deep-link in v2.
//
// Roles are user-facing labels for the agent's work-mode. Internally
// it's still one Edge agent; the role label is just what shows in the
// menu so users see "Risk Scout" / "Historian" / "Decision Clerk"
// instead of an opaque skill name.

export type RitualRole =
  | "historian"
  | "scout"
  | "clerk"
  | "router"
  | "scribe"
  | "reviewer";

export type RitualId =
  | "save"
  | "route"
  | "risk"
  | "why"
  | "handoff"
  | "crystallize";

export interface Ritual {
  id: RitualId;
  // The slash form the user types / sees in the menu.
  command: `/${string}`;
  // Single-character icon. Keep ASCII / emoji minimal — the design
  // system disprefers emoji, but a small glyph helps menu scannability.
  icon: string;
  // The user-facing role label that owns this ritual. Resolved against
  // i18n key `roles.{role}` for both en + zh.
  role: RitualRole;
  // i18n key under `rituals.{id}`. Each ritual has `.label` (menu
  // headline) and `.hint` (one-line description).
  i18nKey: RitualId;
  // The natural-language template inserted into the textarea when the
  // user picks the ritual. {arg} is the user's free-text argument; the
  // template is keyed by locale so the message lands in the user's own
  // language and the Edge agent (which sees recent_turns) keeps voice.
  template: Record<"en" | "zh", string>;
  // Hint text shown above the textarea once a template is active so the
  // user knows what to fill in (e.g., "topic words"). Optional — falls
  // back to the menu hint.
  argHint?: Record<"en" | "zh", string>;
}

// The 6 first-cut rituals. Order matters — this is the menu order.
// Keep it stable across releases so users build muscle memory.
export const RITUALS: readonly Ritual[] = [
  {
    id: "save",
    command: "/save",
    icon: "📚",
    role: "historian",
    i18nKey: "save",
    template: {
      en: "Save the last few turns into team memory: {arg}",
      zh: "把刚才几轮对话存入团队记忆：{arg}",
    },
    argHint: {
      en: "what to capture (topic or anchor message)",
      zh: "想存什么（主题或锚定消息）",
    },
  },
  {
    id: "route",
    command: "/route",
    icon: "🧭",
    role: "router",
    i18nKey: "route",
    template: {
      en: "Find the smallest relevant person on the team for: {arg}",
      zh: "在团队里找最相关的最小群组，主题：{arg}",
    },
    argHint: {
      en: "topic words (2–5)",
      zh: "主题词（2–5 个）",
    },
  },
  {
    id: "risk",
    command: "/risk",
    icon: "⚠",
    role: "scout",
    i18nKey: "risk",
    template: {
      en: "Run a risk scan{arg}",
      zh: "做一次风险扫描{arg}",
    },
    argHint: {
      en: "optional severity floor (low / medium / high)",
      zh: "可选严重度下限（low / medium / high）",
    },
  },
  {
    id: "why",
    command: "/why",
    icon: "🔍",
    role: "clerk",
    i18nKey: "why",
    template: {
      en: "Walk me through the lineage: why {arg}?",
      zh: "解释一下脉络：为什么 {arg}？",
    },
    argHint: {
      en: "what to explain (decision or commitment)",
      zh: "想解释什么（一项决议或承诺）",
    },
  },
  {
    id: "handoff",
    command: "/handoff",
    icon: "🤝",
    role: "scribe",
    i18nKey: "handoff",
    template: {
      en: "Generate a handoff doc for {arg} from the project graph.",
      zh: "为 {arg} 从项目图生成交接文档。",
    },
    argHint: {
      en: "the teammate (display name)",
      zh: "交接对象（显示名）",
    },
  },
  {
    id: "crystallize",
    command: "/crystallize",
    icon: "💠",
    role: "clerk",
    i18nKey: "crystallize",
    template: {
      en: "Crystallize this into a decision: {arg}",
      zh: "把这个凝结为一项决议：{arg}",
    },
    argHint: {
      en: "the call we're making",
      zh: "要凝结的判断",
    },
  },
];

// Map for O(1) lookup by command-prefix during typing. Stable across
// renders because RITUALS is frozen at module load.
const BY_COMMAND = new Map<string, Ritual>(
  RITUALS.map((r) => [r.command, r] as const),
);

export function findRitualByCommand(cmd: string): Ritual | undefined {
  return BY_COMMAND.get(cmd);
}

// Filter rituals matching a prefix the user is typing. Empty prefix
// returns the full menu; non-empty does a startsWith match against the
// command. Used to drive the SlashMenu.
export function filterRituals(prefix: string): readonly Ritual[] {
  if (!prefix || prefix === "/") return RITUALS;
  const lower = prefix.toLowerCase();
  return RITUALS.filter((r) => r.command.toLowerCase().startsWith(lower));
}

// Expand a ritual's template by substituting {arg}. Empty arg leaves
// the placeholder visible so the user sees there's a slot to fill;
// the Composer's send path can detect a literal "{arg}" and treat it
// as "user hasn't filled in yet, suppress send."
export function expandRitual(
  ritual: Ritual,
  arg: string,
  locale: "en" | "zh",
): string {
  const template = ritual.template[locale];
  return template.replace("{arg}", arg);
}
