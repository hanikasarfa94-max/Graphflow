"use client";

// DocumentRightRail — shared spine (Context / Related Work / Evidence
// / AI Assistance / Primary Action) per DESIGN_LOCK invariant #10.
// All right rails on every primary surface follow the same five
// sections in the same order; only the contents change.
//
// AI Assistance buttons return **proposals only**
// (DESIGN_LOCK invariant #4). Clicking them must not mutate state —
// the proposal envelope is then surfaced to the user, who decides.
// The primary action (Publish, the actual state-changing CTA) lives
// in the parent `<DocumentEditor>` sticky footer; we expose the
// "Primary Action" section here only as the doctrine label so the
// rail composition stays consistent across surfaces.

import { Button, Card, Tag, Text } from "@/components/ui";

import type { Document, DocumentRightRailData } from "./types";

// TODO(phase-d.2): wire to `GET /api/right-rail?surface=doc&object_id=...`
// returning a DocumentRightRailData envelope. Phase D mocks the
// content here.
function useDocumentRightRail(doc: Document): DocumentRightRailData {
  return {
    context: {
      scope_id: doc.scope_id,
      scope_label: doc.scope_label,
      last_edited_at: doc.updated_at,
      author: doc.author,
    },
    related_work: [
      { kind: "task", id: "task_marketing_calendar", label: "Marketing calendar" },
      { kind: "topic", id: "topic_launch_date", label: "Topic: launch date" },
    ],
    evidence: [
      { kind: "decision", id: "dec_launch_sep18", label: "Decision: launch Sep 18" },
      { kind: "citation", id: "msg_4218", label: "Mei in #launch · May 12" },
    ],
    ai_assistance: [
      {
        action_id: "summarize",
        label: "Summarize for stakeholders",
        description: "Proposal only — does not modify the document.",
      },
      {
        action_id: "extract_decisions",
        label: "Extract decisions",
        description: "Proposes candidate decisions; you accept each one.",
      },
      {
        action_id: "flag_compression",
        label: "Flag compression risks",
        description: "Highlights ambiguous distillations before publish.",
      },
    ],
  };
}

// TODO(phase-d.2): wire to `POST /api/ai-assistance/run` returning
// `{ proposal, mutates_state: false }`. Phase D logs only.
function useAiAssistance() {
  return (action_id: string, _doc_id: string) => {
    // Proposal-only doctrine — no state mutation happens here.
    // eslint-disable-next-line no-console
    console.info(`[ai-assistance] proposal requested: ${action_id}`);
  };
}

// Hrefs follow the v0.6.2 routing contract — no /projects/...
// allowed. Related-work / evidence links target /docs/[id],
// /scopes/[id], /kb-items/[id], or surface-specific routes.
function hrefForRelated(item: DocumentRightRailData["related_work"][number]): string {
  switch (item.kind) {
    case "task":
      return `/tasks/${item.id}`;
    case "topic":
      return `/conversations/${item.id}`;
    case "doc":
      return `/docs/${item.id}`;
    case "flow_request":
      return `/flow-center?flow_id=${item.id}`;
  }
}

export function DocumentRightRail({ doc }: { doc: Document }) {
  const rail = useDocumentRightRail(doc);
  const runAi = useAiAssistance();

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        width: "100%",
      }}
      aria-label="Document right rail"
    >
      {/* 1. Context */}
      <Section label="Context">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <Text variant="body">
            {/* TODO(i18n) */}
            Scope:{" "}
            <a
              href={`/scopes/${rail.context.scope_id}`}
              style={{ color: "var(--wg-accent)", textDecoration: "none" }}
            >
              {rail.context.scope_label ?? rail.context.scope_id}
            </a>
          </Text>
          {rail.context.author ? (
            <Text variant="caption" muted>
              {/* TODO(i18n) */}
              Author: {rail.context.author.display_name}
            </Text>
          ) : null}
          <Text variant="caption" muted>
            {/* TODO(i18n) */}
            Last edited: {rail.context.last_edited_at}
          </Text>
        </div>
      </Section>

      {/* 2. Related Work */}
      <Section label="Related Work">
        {rail.related_work.length === 0 ? (
          <Text variant="caption" muted>
            {/* TODO(i18n) */}
            Nothing related yet.
          </Text>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {rail.related_work.map((item) => (
              <a
                key={item.id}
                href={hrefForRelated(item)}
                style={{
                  color: "var(--wg-accent)",
                  textDecoration: "none",
                  fontSize: "var(--wg-fs-body)",
                  fontFamily: "var(--wg-font-sans)",
                }}
              >
                <Tag tone="neutral" style={{ marginRight: 6 }}>
                  {item.kind}
                </Tag>
                {item.label}
              </a>
            ))}
          </div>
        )}
      </Section>

      {/* 3. Evidence */}
      <Section label="Evidence">
        {rail.evidence.length === 0 ? (
          <Text variant="caption" muted>
            {/* TODO(i18n) */}
            No evidence linked.
          </Text>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {rail.evidence.map((e) => (
              <div key={e.id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <Tag tone="neutral">{e.kind}</Tag>
                <Text variant="body">{e.label}</Text>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* 4. AI Assistance — proposal-only */}
      <Section label="AI Assistance">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {rail.ai_assistance.map((a) => (
            <div
              key={a.action_id}
              style={{ display: "flex", flexDirection: "column", gap: 4 }}
            >
              <Button
                size="sm"
                variant="ghost"
                onClick={() => runAi(a.action_id, doc.document_id)}
              >
                {a.label}
              </Button>
              <Text variant="caption" muted>
                {a.description}
              </Text>
            </div>
          ))}
          <Card variant="sunk">
            <Text variant="caption" muted>
              {/* TODO(i18n) — doctrine reminder */}
              AI Assistance returns proposals only. State-changing
              actions live in the sticky CTA footer.
            </Text>
          </Card>
        </div>
      </Section>

      {/* 5. Primary Action — label only; actual button is in the
              parent <DocumentEditor> sticky footer (DESIGN_LOCK
              invariant #10: "CTA" is the fifth spine section). */}
      <Section label="Primary Action">
        <Text variant="caption" muted>
          {/* TODO(i18n) */}
          Publish lives in the sticky footer of the editor. Publishing
          proposes memory candidates; acceptance is a separate
          decision.
        </Text>
      </Section>
    </aside>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Text
        variant="caption"
        muted
        style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
      >
        {label}
      </Text>
      {children}
    </section>
  );
}
