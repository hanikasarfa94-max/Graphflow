"use client";

// Documents — page body for /docs. PageHeader + type filter strip +
// DocumentIndex. The doctrine string at the bottom is verbatim from
// DESIGN_LOCK §"Hard invariants" #7.
//
// Phase D scaffold (2026-05-13). Style modelled on
// `apps/web/src/features/flow-center/FlowCenter.tsx`. The scope_id
// param will be sourced from the active ScopeBand selection in Phase
// D.2; for D.1 it's left undefined so the surface shows all visible
// mocks across scopes.

import { useState } from "react";

import { Button, Card, PageHeader, Text } from "@/components/ui";

import { DocumentIndex } from "./DocumentIndex";
import type { DocumentTypeFilter } from "./types";

// Filter strip definitions. Order matches the IA mock — Brief is
// surfaced first after All since it's the doctrine-load-bearing kind.
// TODO(i18n)
const FILTERS: Array<{ id: DocumentTypeFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "brief", label: "Brief" },
  { id: "note", label: "Notes" },
  { id: "attachment", label: "Attachments" },
];

export function Documents() {
  const [filter, setFilter] = useState<DocumentTypeFilter>("all");

  // TODO(phase-d.2): pull `scope_id` from the active ScopeBand
  // selection (currently sourced from /api/user/active-scope on the
  // server side; client hook lands in D.2). Until then, the index
  // mock returns docs across scopes.
  const scope_id: string | undefined = undefined;

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Documents · KB"
        title="Documents"
        subtitle="Project Briefs, design notes, attachments. Authoring is a path to memory candidates — publish proposes memory; it does not accept memory."
      />

      {/* Filter strip — All / Brief / Notes / Attachments */}
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        {FILTERS.map((f) => (
          <Button
            key={f.id}
            size="sm"
            variant={filter === f.id ? "primary" : "ghost"}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      <Card title="Documents" flush>
        <div style={{ padding: 16 }}>
          <DocumentIndex scope_id={scope_id} type={filter} />
        </div>
      </Card>

      <Text
        as="p"
        variant="caption"
        muted
        style={{ marginTop: 16, textAlign: "center" }}
      >
        {/* Doctrine string — DESIGN_LOCK §"Hard invariants" #7. */}
        Memory crystallization is a separate decision.
      </Text>
    </main>
  );
}
