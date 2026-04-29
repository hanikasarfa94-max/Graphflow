"use client";

// ScopeTierPills — N.2 first slice (PLAN-Next.md §"Top bar").
//
// Four inline toggle pills naming the four cell-scope tiers — Personal /
// Cell / Department / Enterprise. Mounted alongside StreamContextPanel
// in StreamCompactToolbar's `actions` slot. Together they answer two
// orthogonal questions about the agent's reach in this turn:
//
//   * StreamContextPanel — what *kinds* of source (graph/kb/dms/audit)
//   * ScopeTierPills    — what *license tiers* (personal/cell/dept/ent)
//
// Wire value alignment: the schema's `KbItemRow.scope` enum keeps the
// legacy 'group' value to mean cell-scope (PLAN-Next §"Schema decisions
// locked 2026-04-28"). The display label says "Cell"; the wire value is
// 'group'. Department + Enterprise are net-new schema values added in
// commit a835887 (B1.1).
//
// Backend wiring follows StreamContextPanel's precedent: this component
// owns localStorage state and broadcasts a window event on change.
// Future consumers (KB queries, attention engine, agent context) can
// listen on SCOPE_TIER_EVENT and intersect with the visible set. The
// backend never trusts the client filter — `LicenseContextService` and
// `KbItemService._assert_can_read` are the access guards. The pills
// are a request-shaping affordance, not an authorization mechanism.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

const TIER_KEYS = ["personal", "group", "department", "enterprise"] as const;
export type ScopeTier = (typeof TIER_KEYS)[number];
export type ScopeTierState = Record<ScopeTier, boolean>;

// All four ON by default — the pills narrow what the user requests, they
// don't widen access. Opening the surface with everything visible matches
// the user's actual permissions on day one (the backend filters anything
// they can't see anyway).
const DEFAULT_STATE: ScopeTierState = {
  personal: true,
  group: true,
  department: true,
  enterprise: true,
};

const STORAGE_PREFIX = "stream:";
const STATE_EVENT = "workgraph:scope-tiers";

function storageKey(projectKey: string): string {
  return `${STORAGE_PREFIX}${projectKey}:scopeTiers`;
}

export function getScopeTiers(projectKey: string): ScopeTierState {
  if (typeof window === "undefined") return { ...DEFAULT_STATE };
  try {
    const raw = window.localStorage.getItem(storageKey(projectKey));
    if (!raw) return { ...DEFAULT_STATE };
    const parsed = JSON.parse(raw) as Partial<ScopeTierState>;
    return { ...DEFAULT_STATE, ...parsed };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

function saveScopeTiers(projectKey: string, state: ScopeTierState): void {
  try {
    window.localStorage.setItem(storageKey(projectKey), JSON.stringify(state));
  } catch {
    // Quota exceeded / private mode — non-fatal.
  }
}

export function ScopeTierPills({ projectKey }: { projectKey: string }) {
  const t = useTranslations("stream.scopeTiers");
  const [state, setState] = useState<ScopeTierState>(DEFAULT_STATE);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setState(getScopeTiers(projectKey));
    setHydrated(true);
  }, [projectKey]);

  const toggle = (k: ScopeTier) => {
    setState((prev) => {
      const next = { ...prev, [k]: !prev[k] };
      saveScopeTiers(projectKey, next);
      window.dispatchEvent(
        new CustomEvent(STATE_EVENT, {
          detail: { projectKey, tiers: next },
        }),
      );
      return next;
    });
  };

  return (
    <div
      role="group"
      aria-label={t("groupLabel")}
      data-testid="scope-tier-pills"
      style={{ display: "flex", alignItems: "center", gap: 4 }}
    >
      {TIER_KEYS.map((k) => (
        <ScopeTierPill
          key={k}
          tier={k}
          label={t(`tier.${k}.label`)}
          hint={t(`tier.${k}.hint`)}
          enabled={hydrated ? state[k] : DEFAULT_STATE[k]}
          onToggle={() => toggle(k)}
        />
      ))}
    </div>
  );
}

function ScopeTierPill({
  tier,
  label,
  hint,
  enabled,
  onToggle,
}: {
  tier: ScopeTier;
  label: string;
  hint: string;
  enabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={enabled}
      title={hint}
      data-tier={tier}
      style={{
        height: 28,
        padding: "0 12px",
        fontSize: 12,
        fontFamily: "var(--wg-font-mono)",
        fontWeight: 600,
        color: enabled ? "var(--wg-accent)" : "var(--wg-ink-soft)",
        background: enabled ? "var(--wg-accent-soft)" : "var(--wg-surface)",
        border: `1px solid ${enabled ? "var(--wg-accent)" : "var(--wg-line)"}`,
        borderRadius: 999,
        cursor: "pointer",
        transition: "background 140ms, color 140ms, border-color 140ms",
        letterSpacing: "0.02em",
      }}
    >
      {label}
    </button>
  );
}

export const SCOPE_TIER_EVENT = STATE_EVENT;
