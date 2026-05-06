// Pure matchers for ProjectModuleRail. Extracted so the active-state
// logic is unit-testable without spinning up a React render harness.
//
// Each module has a `matches(pathname)` predicate that decides whether
// it owns the current URL. Predicates are co-located here (instead of
// inline in ProjectModuleRail.tsx) so the rail's import surface stays
// narrow and the precedence rules below are visible at a glance.

export interface ModuleMatcher {
  key: string;
  href: (base: string) => string;
  matches: (pathname: string, base: string) => boolean;
}

// Order matters for human reading but NOT for active-state. Each
// matcher returns true/false independently; the rail iterates and
// renders all matches as active. To enforce precedence (e.g. "Tasks
// shortcut wins over Audit on /detail/tasks") we make each predicate
// mutually exclusive, not by ordering.
export const MODULE_MATCHERS: ModuleMatcher[] = [
  {
    key: "stream",
    href: (base) => base,
    matches: (p, base) =>
      p === base || p === `${base}/` || p.startsWith(`${base}/rooms/`),
  },
  {
    key: "team",
    href: (base) => `${base}/team`,
    matches: (p, base) => p.startsWith(`${base}/team`),
  },
  {
    key: "status",
    href: (base) => `${base}/status`,
    matches: (p, base) => p.startsWith(`${base}/status`),
  },
  {
    key: "kb",
    href: (base) => `${base}/kb`,
    matches: (p, base) => p.startsWith(`${base}/kb`),
  },
  {
    key: "tasks",
    href: (base) => `${base}/detail/tasks`,
    matches: (p, base) => p.startsWith(`${base}/detail/tasks`),
  },
  {
    // Reviews — direct entry to the Membrane / IMSuggestion review
    // surface at /detail/im. Pre-this-slice the route was orphaned;
    // Audit's permissive prefix-match swept it in.
    key: "reviews",
    href: (base) => `${base}/detail/im`,
    matches: (p, base) => p.startsWith(`${base}/detail/im`),
  },
  {
    // Audit lands on the graph view as the canonical entry. The match
    // list is an explicit allow-list (NOT a permissive `/detail`
    // prefix) so /detail/im (Reviews) and /detail/tasks (Tasks
    // shortcut) don't get swept in.
    key: "audit",
    href: (base) => `${base}/detail/graph`,
    matches: (p, base) =>
      p.startsWith(`${base}/detail/graph`) ||
      p.startsWith(`${base}/detail/plan`) ||
      p.startsWith(`${base}/detail/risks`) ||
      p.startsWith(`${base}/detail/decisions`) ||
      p.startsWith(`${base}/detail/conflicts`) ||
      p.startsWith(`${base}/detail/events`) ||
      p.startsWith(`${base}/detail/delivery`),
  },
  {
    key: "skills",
    href: (base) => `${base}/skills`,
    matches: (p, base) => p.startsWith(`${base}/skills`),
  },
  {
    key: "meetings",
    href: (base) => `${base}/meetings`,
    matches: (p, base) => p.startsWith(`${base}/meetings`),
  },
  {
    key: "renders",
    href: (base) => `${base}/renders`,
    matches: (p, base) => p.startsWith(`${base}/renders`),
  },
  {
    key: "settings",
    href: (base) => `${base}/settings`,
    matches: (p, base) => p.startsWith(`${base}/settings`),
  },
];

// Returns the keys of all modules whose matcher fires for `pathname`.
// In normal operation this is exactly one key; an empty result means
// the pathname is outside every module (project chrome should still
// render but no rail entry highlights).
export function activeModuleKeys(
  pathname: string,
  projectId: string,
): string[] {
  const base = `/projects/${projectId}`;
  return MODULE_MATCHERS.filter((m) => m.matches(pathname, base)).map(
    (m) => m.key,
  );
}
