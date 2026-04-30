// Home-page data aggregator — server-side composition of the signals
// rendered on `/`. There is no dedicated /api/users/me/pending endpoint
// yet (Phase F note), so we compose from the primitives we have:
//
//   * /api/projects           — list the viewer belongs to
//   * /api/projects/{id}/state — for titles, members, active tasks, most
//                                recent decisions
//   * /api/projects/{id}/messages — to harvest pending suggestions whose
//                                   `targets` reference the viewer
//   * /api/streams            — project + DM stream summaries, unread
//
// The aggregator is tolerant — a single project fetch failing must not
// break the whole home. Each per-project fetch is wrapped in try/catch
// and its partial result replaced with a safe default.

import type {
  Decision,
  IMMessage,
  IMSuggestion,
  PendingSignal,
  ProjectState,
  ProjectSummary,
  RoutingInboxResponse,
  RoutingSignal,
  StreamSummary,
  User,
} from "@/lib/api";
import { serverFetch } from "@/lib/auth";

export interface HomeProjectCard {
  id: string;
  title: string;
  role: string;
  last_activity_at: string | null;
  unread_count: number;
  stream_id: string | null;
}

export interface HomeDMCard {
  stream_id: string;
  other_user_id: string;
  other_display_name: string;
  other_username: string;
  last_activity_at: string | null;
  unread_count: number;
  last_message_preview: string | null;
}

export interface ActiveTaskContext {
  kind: "task";
  project_id: string;
  project_title: string;
  task_id: string;
  task_title: string;
  status: string;
  updated_at: string | null;
  upstream_decision: Decision | null;
  downstream_task_titles: string[];
  adjacent_member_names: string[];
}

export interface ActiveDecisionFallback {
  kind: "last_decision";
  project_id: string;
  project_title: string;
  decision_id: string;
  summary: string;
  created_at: string | null;
}

export interface ActiveCaughtUp {
  kind: "caught_up";
  last_crystallization_at: string | null;
}

export type ActiveContext =
  | ActiveTaskContext
  | ActiveDecisionFallback
  | ActiveCaughtUp;

export interface HomeMiniGraphNode {
  id: string;
  title: string;
  /** Maps to the legend chip colour: decision/task/risk/deliverable/goal. */
  kind: "goal" | "deliverable" | "decision" | "task" | "risk";
}

export interface HomeMiniGraphEdge {
  from: string;
  to: string;
}

export interface HomeTopProjectSnapshot {
  project_id: string;
  project_title: string;
  nodes: HomeMiniGraphNode[];
  edges: HomeMiniGraphEdge[];
}

export interface HomePulseAggregates {
  /** Number of project memberships (one per active project). */
  active_project_count: number;
  /** Total graph nodes (goals + deliverables + constraints + risks + tasks) across the viewer's projects. */
  total_graph_nodes: number;
  /** Decisions crystallized in the last 7 days across the viewer's projects. */
  decisions_last_7d: number;
}

export interface HomeData {
  user: User;
  pending: PendingSignal[];
  active: ActiveContext;
  projects: HomeProjectCard[];
  dms: HomeDMCard[];
  /** True when the viewer holds an admin-tier role on any project. Drives
   *  the gated-approvals placeholder section per Phase F §3. */
  is_admin_anywhere: boolean;
  /** System pulse aggregates — drives the hero + pulse card on the
   *  Batch E.3 home rebuild. */
  pulse: HomePulseAggregates;
  /** Snapshot of the most-active project for the home mini-graph
   *  (Batch F.1). Null when the user has no projects. */
  top_project: HomeTopProjectSnapshot | null;
}

function matchesViewer(target: string, user: User): boolean {
  const t = target.trim().toLowerCase();
  if (!t) return false;
  return (
    t === user.id.toLowerCase() ||
    t === user.username.toLowerCase() ||
    t === user.display_name.toLowerCase()
  );
}

function pendingSummary(sug: IMSuggestion, msg: IMMessage | undefined): string {
  // Prefer the suggestion's proposal summary (concise, agent-authored).
  // Fall back to the first ~160 chars of the originating message body.
  const fromProposal = sug.proposal?.summary?.trim();
  if (fromProposal) return fromProposal;
  const reasoning = sug.reasoning?.trim();
  if (reasoning) return reasoning;
  const body = msg?.body?.trim() ?? "";
  if (!body) return "(no preview)";
  return body.length > 160 ? `${body.slice(0, 157)}…` : body;
}

async function fetchProjectMessages(
  projectId: string,
): Promise<{ messages: IMMessage[] }> {
  try {
    return await serverFetch<{ messages: IMMessage[] }>(
      `/api/projects/${projectId}/messages?limit=200`,
    );
  } catch {
    return { messages: [] };
  }
}

async function fetchProjectState(
  projectId: string,
): Promise<ProjectState | null> {
  try {
    return await serverFetch<ProjectState>(`/api/projects/${projectId}/state`);
  } catch {
    return null;
  }
}

export async function loadHomeData(user: User): Promise<HomeData> {
  // --- Projects + streams + routing-inbox in parallel ---
  // Routing inbox is fetched here so home can include peer-routed asks
  // in the "needs your response" list — matches what the sidebar
  // inbox badge counts, so the two surfaces stay aligned.
  const [projects, streamsResp, routingResp] = await Promise.all([
    serverFetch<ProjectSummary[]>(`/api/projects`).catch(
      () => [] as ProjectSummary[],
    ),
    serverFetch<{ streams: StreamSummary[] }>(`/api/streams`).catch(
      () => ({ streams: [] as StreamSummary[] }),
    ),
    serverFetch<RoutingInboxResponse>(
      `/api/routing/inbox?status=pending&limit=50`,
    ).catch(() => ({ signals: [] as RoutingSignal[] })),
  ]);
  const streams = streamsResp.streams ?? [];
  const routingSignals = routingResp.signals ?? [];

  // Index project streams by project_id for unread lookup + mark-read.
  const projectStreamByProjectId = new Map<string, StreamSummary>();
  for (const s of streams) {
    if (s.type === "project" && s.project_id) {
      projectStreamByProjectId.set(s.project_id, s);
    }
  }

  // Project cards — merge ProjectSummary + stream unread.
  const projectCards: HomeProjectCard[] = projects.map((p) => {
    const s = projectStreamByProjectId.get(p.id);
    return {
      id: p.id,
      title: p.title,
      role: p.role,
      last_activity_at: s?.last_activity_at ?? p.updated_at ?? null,
      unread_count: s?.unread_count ?? 0,
      stream_id: s?.id ?? null,
    };
  });
  // Most-recent first.
  projectCards.sort((a, b) => {
    const at = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
    const bt = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
    return bt - at;
  });

  // DM cards.
  const dmCards: HomeDMCard[] = streams
    .filter((s) => s.type === "dm")
    .map((s) => {
      const other = s.members.find((m) => m.user_id !== user.id);
      return {
        stream_id: s.id,
        other_user_id: other?.user_id ?? "",
        other_display_name:
          other?.display_name ?? other?.username ?? "(unknown)",
        other_username: other?.username ?? "",
        last_activity_at: s.last_activity_at,
        unread_count: s.unread_count,
        last_message_preview: null, // not on the stream summary yet
      };
    })
    .sort((a, b) => {
      const at = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
      const bt = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
      return bt - at;
    });

  // --- Per-project: messages for pending, state for active-task ---
  // Fetch in parallel. Each is independently tolerant.
  const perProject = await Promise.all(
    projects.map(async (p) => {
      const [messagesResp, state] = await Promise.all([
        fetchProjectMessages(p.id),
        fetchProjectState(p.id),
      ]);
      return { project: p, messages: messagesResp.messages, state };
    }),
  );

  // Build pending signals across all projects.
  const pending: PendingSignal[] = [];
  let isAdminAnywhere = false;
  for (const { project, messages, state } of perProject) {
    // Admin check — Phase F §3 proxy: ProjectMemberRow.role is admin-like
    // (owner/admin). The backend has no "approver role" primitive yet, so
    // we err on the side of surfacing the placeholder to anyone in a
    // leadership position on any project.
    if (
      state?.members.some(
        (m) =>
          m.user_id === user.id &&
          (m.role === "admin" || m.role === "owner"),
      )
    ) {
      isAdminAnywhere = true;
    }
    for (const m of messages) {
      const sug = m.suggestion;
      if (!sug || sug.status !== "pending") continue;
      // Viewer-directed? `targets` is free-form IDs/usernames/roles.
      // Empty-targets suggestions are broadcast to the whole project —
      // we include decision/blocker kinds because those are the ones a
      // member is expected to accept/counter anyway.
      const directed = sug.targets.some((t) => matchesViewer(t, user));
      const broadcast =
        sug.targets.length === 0 && (sug.kind === "decision" || sug.kind === "blocker");
      if (!directed && !broadcast) continue;
      pending.push({
        suggestion_id: sug.id,
        message_id: m.id,
        project_id: project.id,
        project_title: project.title,
        summary: pendingSummary(sug, m),
        kind: sug.kind,
        created_at: sug.created_at,
        jump_href: `/projects/${project.id}#msg-${m.id}`,
      });
    }
  }
  // Routing-inbox signals — peer-routed asks that haven't been answered
  // yet. Mapped into the same PendingSignal shape so the home
  // "needs your response" list shows IM suggestions and routing asks
  // in one flow, ordered by created_at. Project title is looked up
  // from the projects array; falls back to the project id when the
  // signal references a project the viewer no longer belongs to.
  const projectTitleById = new Map<string, string>(
    projects.map((p) => [p.id, p.title]),
  );
  for (const s of routingSignals) {
    if (s.target_user_id !== user.id) continue;
    if (s.status !== "pending") continue;
    pending.push({
      suggestion_id: `routing-${s.id}`,
      message_id: s.target_stream_id,
      project_id: s.project_id,
      project_title: projectTitleById.get(s.project_id) ?? s.project_id,
      summary: s.framing || "(routed ask)",
      kind: "routing",
      created_at: s.created_at ?? new Date(0).toISOString(),
      jump_href: `/inbox`,
    });
  }
  // Most recent first.
  pending.sort((a, b) => {
    const at = new Date(a.created_at).getTime();
    const bt = new Date(b.created_at).getTime();
    return bt - at;
  });

  // --- Active-task context ---
  // Look across all projects for a task assigned to the viewer whose
  // status is NOT done/canceled, most-recently-updated wins. Fall back
  // to the last-decision summary if no assigned task, else "caught up".
  let active: ActiveContext;
  const candidateTasks: Array<{
    project_id: string;
    project_title: string;
    task: ProjectState["plan"]["tasks"][number];
    members: ProjectState["members"];
    decisions: ProjectState["decisions"];
    dependencies: ProjectState["plan"]["dependencies"];
    allTasks: ProjectState["plan"]["tasks"];
    updated_at: string | null;
  }> = [];
  let fallbackLastDecision: {
    project_id: string;
    project_title: string;
    decision: Decision;
  } | null = null;
  let newestCrystallizationAt: string | null = null;
  for (const { project, state } of perProject) {
    if (!state) continue;
    // Track newest crystallization across all projects for the
    // "All caught up — last crystallization: X" polish.
    for (const d of state.decisions) {
      if (!d.created_at) continue;
      if (
        newestCrystallizationAt === null ||
        new Date(d.created_at).getTime() >
          new Date(newestCrystallizationAt).getTime()
      ) {
        newestCrystallizationAt = d.created_at;
      }
    }
    // Candidate tasks assigned to the viewer, active status.
    const myAssignments = state.assignments.filter(
      (a) => a.user_id === user.id && a.active,
    );
    const myTaskIds = new Set(myAssignments.map((a) => String(a.task_id)));
    for (const t of state.plan.tasks) {
      if (!myTaskIds.has(t.id)) continue;
      if (t.status === "done" || t.status === "cancelled") continue;
      // ProjectState.tasks doesn't carry updated_at explicitly — use the
      // project-level updated_at as a proxy for "most recent".
      candidateTasks.push({
        project_id: project.id,
        project_title: project.title,
        task: t,
        members: state.members,
        decisions: state.decisions,
        dependencies: state.plan.dependencies,
        allTasks: state.plan.tasks,
        updated_at: state.decisions[0]?.created_at ?? null,
      });
    }
    // Track fallback: the most recent decision across any project.
    if (state.decisions.length > 0) {
      const d = state.decisions[0]; // list_for_project returns newest first
      if (
        fallbackLastDecision === null ||
        (d.created_at &&
          fallbackLastDecision.decision.created_at &&
          new Date(d.created_at).getTime() >
            new Date(fallbackLastDecision.decision.created_at).getTime())
      ) {
        fallbackLastDecision = {
          project_id: project.id,
          project_title: project.title,
          decision: d,
        };
      }
    }
  }

  if (candidateTasks.length > 0) {
    // "Most recently updated" proxy — sort by decision-timestamp on the
    // owning project (a coarse but fine-for-v1 signal) then fall back
    // to task title for determinism.
    candidateTasks.sort((a, b) => {
      const at = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const bt = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return bt - at;
    });
    const top = candidateTasks[0];
    // Upstream decision: look for a decision whose source task/ref matches
    // the task. Backend exposes source_suggestion_id but not a direct
    // task edge — for v1, any decision on the same project that predates
    // the task counts as ambient upstream. We pick the most-recent one.
    const upstream = top.decisions.length > 0 ? top.decisions[0] : null;
    // Downstream: tasks this one unblocks via the dependency graph.
    const downstreamIds = top.dependencies
      .filter((d) => d.from_task_id === top.task.id)
      .map((d) => d.to_task_id);
    const downstreamTitles = top.allTasks
      .filter((t) => downstreamIds.includes(t.id))
      .map((t) => t.title);
    // Adjacent members: anyone else on the project with an active, non-
    // done task (up to 5 names).
    const adjacentNames: string[] = top.members
      .filter((m) => m.user_id !== user.id)
      .slice(0, 5)
      .map((m) => m.display_name || m.username);
    active = {
      kind: "task",
      project_id: top.project_id,
      project_title: top.project_title,
      task_id: top.task.id,
      task_title: top.task.title,
      status: top.task.status,
      updated_at: top.updated_at,
      upstream_decision: upstream,
      downstream_task_titles: downstreamTitles,
      adjacent_member_names: adjacentNames,
    };
  } else if (fallbackLastDecision !== null) {
    active = {
      kind: "last_decision",
      project_id: fallbackLastDecision.project_id,
      project_title: fallbackLastDecision.project_title,
      decision_id: fallbackLastDecision.decision.id,
      summary:
        fallbackLastDecision.decision.rationale ||
        fallbackLastDecision.decision.custom_text ||
        "(decision recorded)",
      created_at: fallbackLastDecision.decision.created_at,
    };
  } else {
    active = {
      kind: "caught_up",
      last_crystallization_at: newestCrystallizationAt,
    };
  }

  // Pulse aggregates — derive from data already in hand. Cheap.
  //
  // Graph nodes counted: goals + deliverables + risks + tasks +
  // decisions. Constraints are intentionally excluded — they're a
  // side-channel of risks (severity-coded blockers) and would
  // double-count what `risks` already captures. Decisions ARE counted
  // because the audit-graph view treats them as first-class nodes
  // (see html2 audit panel). Net: matches what the user sees totalled
  // across the per-project Status page metrics.
  //
  // Decisions in the last 7d count: skip apply_outcome="failed" — a
  // decision whose mechanical follow-through failed isn't a
  // crystallized one, so it shouldn't pad the weekly cadence number.
  const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  let totalGraphNodes = 0;
  let decisionsLast7d = 0;
  for (const { state } of perProject) {
    if (!state) continue;
    totalGraphNodes +=
      (state.graph?.goals?.length ?? 0) +
      (state.graph?.deliverables?.length ?? 0) +
      (state.graph?.risks?.length ?? 0) +
      (state.plan?.tasks?.length ?? 0) +
      (state.decisions?.length ?? 0);
    for (const d of state.decisions) {
      if (!d.created_at) continue;
      if (d.apply_outcome === "failed") continue;
      if (new Date(d.created_at).getTime() >= sevenDaysAgo) {
        decisionsLast7d += 1;
      }
    }
  }

  // Top-project snapshot for the home mini-graph (Batch F.1). Pick the
  // most-recently-active project for which we have a state payload, then
  // surface up to 5 of its most-relevant nodes (goal, deliverable,
  // decision, task, risk in roughly that priority) and a few connecting
  // edges from the dependency list.
  let topProject: HomeTopProjectSnapshot | null = null;
  const orderedProjects = perProject.filter((p) => p.state !== null);
  // Sort by the same activity proxy used for the project cards: stream
  // last_activity_at if available, else project.updated_at.
  orderedProjects.sort((a, b) => {
    const aTime = projectStreamByProjectId.get(a.project.id)?.last_activity_at
      ?? a.project.updated_at ?? null;
    const bTime = projectStreamByProjectId.get(b.project.id)?.last_activity_at
      ?? b.project.updated_at ?? null;
    const at = aTime ? new Date(aTime).getTime() : 0;
    const bt = bTime ? new Date(bTime).getTime() : 0;
    return bt - at;
  });
  const top = orderedProjects[0];
  if (top && top.state) {
    const nodes: HomeMiniGraphNode[] = [];
    const pushNode = (id: string, title: string, kind: HomeMiniGraphNode["kind"]) => {
      if (nodes.length >= 5 || !id || !title) return;
      nodes.push({ id, title, kind });
    };
    for (const g of top.state.graph?.goals ?? []) pushNode(g.id, g.title, "goal");
    for (const d of top.state.graph?.deliverables ?? []) pushNode(d.id, d.title, "deliverable");
    for (const dec of top.state.decisions.slice(0, 2))
      pushNode(dec.id, dec.rationale || dec.custom_text || "decision", "decision");
    for (const t of top.state.plan.tasks ?? []) pushNode(t.id, t.title, "task");
    for (const r of top.state.graph?.risks ?? []) pushNode(r.id, r.title, "risk");
    const knownIds = new Set(nodes.map((n) => n.id));
    const edges: HomeMiniGraphEdge[] = [];
    for (const dep of top.state.plan.dependencies ?? []) {
      if (edges.length >= 4) break;
      if (knownIds.has(dep.from_task_id) && knownIds.has(dep.to_task_id)) {
        edges.push({ from: dep.from_task_id, to: dep.to_task_id });
      }
    }
    topProject = {
      project_id: top.project.id,
      project_title: top.project.title,
      nodes,
      edges,
    };
  }

  return {
    user,
    pending,
    active,
    projects: projectCards,
    dms: dmCards,
    is_admin_anywhere: isAdminAnywhere,
    pulse: {
      active_project_count: projects.length,
      total_graph_nodes: totalGraphNodes,
      decisions_last_7d: decisionsLast7d,
    },
    top_project: topProject,
  };
}
