"use client";

// AuthorityState — renders the server-computed authority_check for a
// flow request or memory candidate. NEVER infers permission from
// local role strings (CLAUDE.md invariant: "License gate is single-
// source"; FRONTEND_IMPLEMENTATION.md: "Frontend should render from
// authority_check, not infer from local role strings").
//
// If `can_accept` is false, the consuming component must disable its
// primary action and surface the "Request review from {required_role}"
// affordance. This component renders only the read-only state block;
// the disabled CTA is the caller's responsibility because the CTA
// label varies by surface (Accept memory, Accept flow, Promote task,
// Publish doc, Resolve topic).

import { Tag, Text } from "@/components/ui";

import type { AuthorityCheck } from "./types";

export function AuthorityState({ check }: { check: AuthorityCheck }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface-sunk)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Text variant="caption" muted>
          Authority
        </Text>
        <Tag tone={check.can_accept ? "ok" : "amber"}>
          {check.can_accept ? "can accept" : "review required"}
        </Tag>
      </div>
      <Row label="Required roles">
        {check.required_roles.length > 0
          ? check.required_roles.map((r) => (
              <Tag key={r} tone="neutral">
                {r}
              </Tag>
            ))
          : "—"}
      </Row>
      <Row label="Your roles">
        {check.user_roles.length > 0
          ? check.user_roles.map((r) => (
              <Tag key={r} tone="accent">
                {r}
              </Tag>
            ))
          : "—"}
      </Row>
      <Row label="Allowed actions">
        {check.allowed_actions.length > 0
          ? check.allowed_actions.map((a) => (
              <Tag key={a} tone="neutral">
                {a}
              </Tag>
            ))
          : "—"}
      </Row>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <Text
        variant="caption"
        muted
        style={{ minWidth: 110, textTransform: "uppercase", letterSpacing: "0.06em" }}
      >
        {label}
      </Text>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{children}</div>
    </div>
  );
}
