import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import type { ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

// /projects/[id]/nodes/[nodeId] — deep-link landing for any graph
// entity. Resolves the bare UUID against every kind in the project's
// /state payload (task, decision, risk, deliverable, goal, milestone,
// commitment, conflict) and renders a kind-specific detail + lineage
// view.
//
// This is the page why-chain citations point at: a cited decision
// card links here, and here the viewer sees the decision's full
// rationale, its originating conflict, the entities that conflict
// touched, and a back-link to the graph.

type NodeKind =
  | "task"
  | "decision"
  | "risk"
  | "deliverable"
  | "goal"
  | "milestone"
  | "commitment"
  | "conflict";

interface ResolvedNode {
  kind: NodeKind;
  id: string;
  title: string;
  raw: Record<string, unknown>;
}

function resolve(state: ProjectState, nodeId: string): ResolvedNode | null {
  for (const g of state.graph.goals) {
    if (g.id === nodeId) {
      return { kind: "goal", id: g.id, title: g.title, raw: g };
    }
  }
  for (const d of state.graph.deliverables) {
    if (d.id === nodeId) {
      return { kind: "deliverable", id: d.id, title: d.title, raw: d };
    }
  }
  for (const r of state.graph.risks) {
    if (r.id === nodeId) {
      return { kind: "risk", id: r.id, title: r.title, raw: r };
    }
  }
  for (const t of state.plan.tasks) {
    if (t.id === nodeId) {
      return { kind: "task", id: t.id, title: t.title, raw: t };
    }
  }
  for (const m of state.plan.milestones) {
    if (m.id === nodeId) {
      return { kind: "milestone", id: m.id, title: m.title, raw: m };
    }
  }
  for (const dec of state.decisions) {
    if (dec.id === nodeId) {
      const title =
        (dec.custom_text && dec.custom_text.split("\n")[0]) ||
        (dec.rationale && dec.rationale.split(/[.。!?!?\n]/)[0]) ||
        "(unlabelled decision)";
      return {
        kind: "decision",
        id: dec.id,
        title: title.slice(0, 120),
        raw: dec as unknown as Record<string, unknown>,
      };
    }
  }
  for (const c of state.conflicts) {
    if (c.id === nodeId) {
      return {
        kind: "conflict",
        id: c.id,
        title: c.summary || c.rule,
        raw: c as unknown as Record<string, unknown>,
      };
    }
  }
  for (const cm of state.commitments ?? []) {
    if (cm.id === nodeId) {
      return {
        kind: "commitment",
        id: cm.id,
        title: cm.headline,
        raw: cm as unknown as Record<string, unknown>,
      };
    }
  }
  return null;
}

// -- kind-specific lineage builders ----------------------------------------

function taskLineage(node: ResolvedNode, state: ProjectState) {
  const taskId = node.id;
  const depsOn = state.plan.dependencies
    .filter((d) => d.to_task_id === taskId)
    .map((d) => state.plan.tasks.find((t) => t.id === d.from_task_id))
    .filter(Boolean) as ProjectState["plan"]["tasks"];
  const blocks = state.plan.dependencies
    .filter((d) => d.from_task_id === taskId)
    .map((d) => state.plan.tasks.find((t) => t.id === d.to_task_id))
    .filter(Boolean) as ProjectState["plan"]["tasks"];
  const commitments = (state.commitments ?? []).filter(
    (c) => c.scope_ref_kind === "task" && c.scope_ref_id === taskId,
  );
  const milestones = state.plan.milestones.filter((m) =>
    (m.related_task_ids ?? []).includes(taskId),
  );
  const decisions = state.decisions.filter((d) => {
    if (!d.conflict_id) return false;
    const c = state.conflicts.find((cx) => cx.id === d.conflict_id);
    return !!c && c.targets.includes(taskId);
  });
  return { depsOn, blocks, commitments, milestones, decisions };
}

function decisionLineage(node: ResolvedNode, state: ProjectState) {
  const dec = state.decisions.find((d) => d.id === node.id)!;
  const conflict = dec.conflict_id
    ? state.conflicts.find((c) => c.id === dec.conflict_id) ?? null
    : null;
  const targetEntities: { kind: string; id: string; title: string }[] = [];
  if (conflict) {
    for (const tid of conflict.targets) {
      const t = state.plan.tasks.find((x) => x.id === tid);
      if (t) {
        targetEntities.push({ kind: "task", id: t.id, title: t.title });
        continue;
      }
      const r = state.graph.risks.find((x) => x.id === tid);
      if (r) {
        targetEntities.push({ kind: "risk", id: r.id, title: r.title });
        continue;
      }
      const d = state.graph.deliverables.find((x) => x.id === tid);
      if (d) {
        targetEntities.push({
          kind: "deliverable",
          id: d.id,
          title: d.title,
        });
        continue;
      }
      const g = state.graph.goals.find((x) => x.id === tid);
      if (g) {
        targetEntities.push({ kind: "goal", id: g.id, title: g.title });
      }
    }
  }
  return { dec, conflict, targetEntities };
}

function commitmentLineage(node: ResolvedNode, state: ProjectState) {
  const cm = (state.commitments ?? []).find((c) => c.id === node.id)!;
  let anchor: { kind: string; id: string; title: string } | null = null;
  if (cm.scope_ref_kind && cm.scope_ref_id) {
    const id = cm.scope_ref_id;
    switch (cm.scope_ref_kind) {
      case "task": {
        const t = state.plan.tasks.find((x) => x.id === id);
        if (t) anchor = { kind: "task", id: t.id, title: t.title };
        break;
      }
      case "deliverable": {
        const d = state.graph.deliverables.find((x) => x.id === id);
        if (d) anchor = { kind: "deliverable", id: d.id, title: d.title };
        break;
      }
      case "goal": {
        const g = state.graph.goals.find((x) => x.id === id);
        if (g) anchor = { kind: "goal", id: g.id, title: g.title };
        break;
      }
      case "milestone": {
        const m = state.plan.milestones.find((x) => x.id === id);
        if (m) anchor = { kind: "milestone", id: m.id, title: m.title };
        break;
      }
    }
  }
  return { cm, anchor };
}

// -- page ------------------------------------------------------------------

export default async function NodeDetailPage({
  params,
}: {
  params: Promise<{ id: string; nodeId: string }>;
}) {
  const { id: projectId, nodeId } = await params;
  const t = await getTranslations("nodeDetail");

  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${projectId}/state`);
  } catch {
    state = null;
  }
  if (!state) {
    // 403 bubbles through serverFetch as null; treat as unavailable.
    return <Unavailable projectId={projectId} label={t("unavailable")} />;
  }
  const node = resolve(state, nodeId);
  if (!node) {
    notFound();
  }

  return (
    <main
      style={{
        maxWidth: 880,
        margin: "0 auto",
        padding: "40px 24px 80px",
        fontFamily: "var(--wg-font-sans)",
      }}
    >
      <BackStrip projectId={projectId} label={t("backToGraph")} />
      <Header node={node} labels={{ kind: t(`kinds.${node.kind}`) }} />
      <KindSpecific node={node} state={state} projectId={projectId} t={t} />
      <FooterLinks
        projectId={projectId}
        nodeId={nodeId}
        labels={{
          openInGraph: t("openInGraph"),
        }}
      />
    </main>
  );
}

// -- pieces ----------------------------------------------------------------

function Unavailable({
  projectId,
  label,
}: {
  projectId: string;
  label: string;
}) {
  return (
    <main
      style={{
        maxWidth: 640,
        margin: "0 auto",
        padding: "80px 24px",
        textAlign: "center",
      }}
    >
      <p
        style={{
          color: "var(--wg-ink-faint)",
          fontSize: 14,
          marginBottom: 20,
        }}
      >
        {label}
      </p>
      <Link
        href={`/projects/${projectId}`}
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-accent)",
        }}
      >
        ← {projectId.slice(0, 8)}
      </Link>
    </main>
  );
}

function BackStrip({
  projectId,
  label,
}: {
  projectId: string;
  label: string;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Link
        href={`/projects/${projectId}/detail/graph`}
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          textDecoration: "none",
        }}
      >
        ← {label}
      </Link>
    </div>
  );
}

function Header({
  node,
  labels,
}: {
  node: ResolvedNode;
  labels: { kind: string };
}) {
  return (
    <header style={{ marginBottom: 24 }}>
      <div
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-accent)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          marginBottom: 6,
        }}
      >
        {labels.kind}
      </div>
      <h1
        style={{
          margin: 0,
          fontSize: 24,
          lineHeight: 1.3,
          color: "var(--wg-ink)",
          wordBreak: "break-word",
        }}
      >
        {node.title || "(no title)"}
      </h1>
      <div
        style={{
          marginTop: 4,
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
        }}
      >
        id: {node.id}
      </div>
    </header>
  );
}

// Kind-specific body — delegates to per-kind sections. Each block is
// a collection of Rows + optional sub-lists. Kept in one component so
// the page stays one file; we can split later if it grows past 600 LOC.
function KindSpecific({
  node,
  state,
  projectId,
  t,
}: {
  node: ResolvedNode;
  state: ProjectState;
  projectId: string;
  // next-intl's useTranslations return; typed loose so we can pass it
  // through without plumbing every key through the component signature.
  t: (key: string) => string;
}) {
  switch (node.kind) {
    case "task":
      return <TaskSection node={node} state={state} projectId={projectId} t={t} />;
    case "decision":
      return <DecisionSection node={node} state={state} projectId={projectId} t={t} />;
    case "commitment":
      return <CommitmentSection node={node} state={state} projectId={projectId} t={t} />;
    case "risk":
    case "deliverable":
    case "goal":
    case "milestone":
    case "conflict":
      return <SimpleSection node={node} t={t} />;
  }
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        fontSize: 13,
        padding: "6px 0",
        borderBottom: "1px solid var(--wg-line-soft)",
        gap: 16,
      }}
    >
      <div
        style={{
          width: 140,
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {k}
      </div>
      <div style={{ flex: 1, color: "var(--wg-ink)" }}>{v}</div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginTop: 28 }}>
      <h3
        style={{
          margin: "0 0 10px",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {title}
      </h3>
      <div>{children}</div>
    </section>
  );
}

function NodeLinkChip({
  projectId,
  kind,
  id,
  title,
}: {
  projectId: string;
  kind: string;
  id: string;
  title: string;
}) {
  return (
    <Link
      href={`/projects/${projectId}/nodes/${id}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 10px",
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: 4,
        fontSize: 12,
        color: "var(--wg-ink)",
        textDecoration: "none",
        marginRight: 6,
        marginBottom: 6,
      }}
    >
      <span
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {kind}
      </span>
      <span>{title || id.slice(0, 8)}</span>
    </Link>
  );
}

// ---- Task ----------------------------------------------------------------

function TaskSection({
  node,
  state,
  projectId,
  t,
}: {
  node: ResolvedNode;
  state: ProjectState;
  projectId: string;
  t: (key: string) => string;
}) {
  const task = node.raw as ProjectState["plan"]["tasks"][number];
  const { depsOn, blocks, commitments, milestones, decisions } = taskLineage(
    node,
    state,
  );
  return (
    <>
      <Section title={t("sections.basics")}>
        {task.status ? <Row k={t("rows.status")} v={task.status} /> : null}
        {task.assignee_role ? (
          <Row k={t("rows.assignee")} v={task.assignee_role} />
        ) : null}
        {task.estimate_hours != null ? (
          <Row k={t("rows.estimate")} v={`${task.estimate_hours}h`} />
        ) : null}
        {task.deliverable_id ? (
          <Row
            k={t("rows.deliverable")}
            v={
              <DeliverableLink
                projectId={projectId}
                state={state}
                id={task.deliverable_id}
              />
            }
          />
        ) : null}
      </Section>
      {task.description ? (
        <Section title={t("sections.description")}>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
            {task.description}
          </p>
        </Section>
      ) : null}
      {task.acceptance_criteria && task.acceptance_criteria.length > 0 ? (
        <Section title={t("sections.acceptance")}>
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13, lineHeight: 1.6 }}>
            {task.acceptance_criteria.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </Section>
      ) : null}
      {depsOn.length > 0 ? (
        <Section title={t("sections.dependsOn")}>
          <div>
            {depsOn.map((d) => (
              <NodeLinkChip
                key={d.id}
                projectId={projectId}
                kind="task"
                id={d.id}
                title={d.title}
              />
            ))}
          </div>
        </Section>
      ) : null}
      {blocks.length > 0 ? (
        <Section title={t("sections.blocks")}>
          <div>
            {blocks.map((d) => (
              <NodeLinkChip
                key={d.id}
                projectId={projectId}
                kind="task"
                id={d.id}
                title={d.title}
              />
            ))}
          </div>
        </Section>
      ) : null}
      {commitments.length > 0 ? (
        <Section title={t("sections.boundCommitments")}>
          <div>
            {commitments.map((c) => (
              <NodeLinkChip
                key={c.id}
                projectId={projectId}
                kind="commitment"
                id={c.id}
                title={c.headline}
              />
            ))}
          </div>
        </Section>
      ) : null}
      {milestones.length > 0 ? (
        <Section title={t("sections.milestones")}>
          <div>
            {milestones.map((m) => (
              <NodeLinkChip
                key={m.id}
                projectId={projectId}
                kind="milestone"
                id={m.id}
                title={m.title}
              />
            ))}
          </div>
        </Section>
      ) : null}
      {decisions.length > 0 ? (
        <Section title={t("sections.touchedByDecisions")}>
          <div>
            {decisions.map((d) => (
              <NodeLinkChip
                key={d.id}
                projectId={projectId}
                kind="decision"
                id={d.id}
                title={
                  (d.custom_text ?? "").split("\n")[0] ||
                  (d.rationale ?? "").split(/[.。!?!?\n]/)[0] ||
                  "(decision)"
                }
              />
            ))}
          </div>
        </Section>
      ) : null}
    </>
  );
}

function DeliverableLink({
  projectId,
  state,
  id,
}: {
  projectId: string;
  state: ProjectState;
  id: string;
}) {
  const d = state.graph.deliverables.find((x) => x.id === id);
  return (
    <NodeLinkChip
      projectId={projectId}
      kind="deliverable"
      id={id}
      title={d?.title ?? id.slice(0, 8)}
    />
  );
}

// ---- Decision ------------------------------------------------------------

function DecisionSection({
  node,
  state,
  projectId,
  t,
}: {
  node: ResolvedNode;
  state: ProjectState;
  projectId: string;
  t: (key: string) => string;
}) {
  const { dec, conflict, targetEntities } = decisionLineage(node, state);
  return (
    <>
      <Section title={t("sections.basics")}>
        {dec.apply_outcome ? (
          <Row k={t("rows.status")} v={dec.apply_outcome} />
        ) : null}
        {dec.created_at ? (
          <Row k={t("rows.when")} v={new Date(dec.created_at).toLocaleString()} />
        ) : null}
      </Section>
      {dec.rationale ? (
        <Section title={t("sections.rationale")}>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
            {dec.rationale}
          </p>
        </Section>
      ) : null}
      {conflict ? (
        <Section title={t("sections.originatingConflict")}>
          <p
            style={{
              margin: 0,
              fontSize: 13,
              lineHeight: 1.55,
              color: "var(--wg-ink-soft)",
              fontStyle: "italic",
              borderLeft: "2px solid var(--wg-line)",
              paddingLeft: 10,
            }}
          >
            {conflict.summary || conflict.rule}
          </p>
        </Section>
      ) : null}
      {targetEntities.length > 0 ? (
        <Section title={t("sections.touched")}>
          <div>
            {targetEntities.map((e) => (
              <NodeLinkChip
                key={e.id}
                projectId={projectId}
                kind={e.kind}
                id={e.id}
                title={e.title}
              />
            ))}
          </div>
        </Section>
      ) : null}
    </>
  );
}

// ---- Commitment ----------------------------------------------------------

function CommitmentSection({
  node,
  state,
  projectId,
  t,
}: {
  node: ResolvedNode;
  state: ProjectState;
  projectId: string;
  t: (key: string) => string;
}) {
  const { cm, anchor } = commitmentLineage(node, state);
  return (
    <>
      <Section title={t("sections.basics")}>
        <Row k={t("rows.status")} v={cm.status} />
        {cm.target_date ? (
          <Row
            k={t("rows.target")}
            v={new Date(cm.target_date).toLocaleDateString()}
          />
        ) : null}
        {cm.sla_window_seconds ? (
          <Row
            k={t("rows.slaWindow")}
            v={`${Math.round(cm.sla_window_seconds / 86400)}d`}
          />
        ) : null}
        {cm.metric ? <Row k={t("rows.metric")} v={cm.metric} /> : null}
      </Section>
      {anchor ? (
        <Section title={t("sections.anchor")}>
          <NodeLinkChip
            projectId={projectId}
            kind={anchor.kind}
            id={anchor.id}
            title={anchor.title}
          />
        </Section>
      ) : null}
    </>
  );
}

// ---- Simple (risk / deliverable / goal / milestone / conflict) -----------

function SimpleSection({
  node,
  t,
}: {
  node: ResolvedNode;
  t: (key: string) => string;
}) {
  const raw = node.raw;
  const rows: { k: string; v: string }[] = [];
  for (const field of [
    "status",
    "severity",
    "kind",
    "target_date",
    "rule",
  ] as const) {
    const v = raw[field];
    if (typeof v === "string" && v) {
      rows.push({ k: t(`rows.${field}`), v });
    }
  }
  const desc =
    typeof raw.description === "string"
      ? raw.description
      : typeof raw.content === "string"
        ? raw.content
        : typeof raw.summary === "string"
          ? raw.summary
          : null;
  return (
    <>
      {rows.length > 0 ? (
        <Section title={t("sections.basics")}>
          {rows.map((r) => (
            <Row key={r.k} k={r.k} v={r.v} />
          ))}
        </Section>
      ) : null}
      {desc ? (
        <Section title={t("sections.description")}>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
            {desc}
          </p>
        </Section>
      ) : null}
    </>
  );
}

// ---- Footer --------------------------------------------------------------

function FooterLinks({
  projectId,
  nodeId,
  labels,
}: {
  projectId: string;
  nodeId: string;
  labels: { openInGraph: string };
}) {
  return (
    <footer
      style={{
        marginTop: 40,
        paddingTop: 16,
        borderTop: "1px solid var(--wg-line)",
        display: "flex",
        gap: 16,
      }}
    >
      <Link
        href={`/projects/${projectId}/detail/graph#${nodeId}`}
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-accent)",
          textDecoration: "none",
        }}
      >
        {labels.openInGraph} →
      </Link>
    </footer>
  );
}
