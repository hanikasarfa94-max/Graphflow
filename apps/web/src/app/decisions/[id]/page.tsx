// /decisions/[id] — decision read-only proof page.
//
// Phase RW-6 (2026-05-13): the Phase E.1 placeholder is replaced
// with a real read-only body sourced from the live
// GET /api/decisions/:id endpoint added in this slice (wraps
// DecisionService.get_for_viewer, membership-gated).
//
// Renders the truthful decision fields the BE exposes today: id,
// scope, conflict_id, resolver_id, option_index, custom_text,
// rationale, apply_outcome, apply_detail, created_at, applied_at.
// No mutation. No fabricated lineage. Vote tally is fetched
// best-effort via the existing /api/decisions/:id/votes endpoint;
// failure to load it does not block the page.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Card, EmptyState, PageHeader, Tag, Text } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

type DecisionDetail = {
  id: string;
  conflict_id: string | null;
  source_suggestion_id: string | null;
  project_id: string | null;
  resolver_id: string | null;
  option_index: number | null;
  custom_text: string | null;
  rationale: string | null;
  apply_actions: Array<{ kind: string; [k: string]: unknown }>;
  apply_outcome: string | null;
  apply_detail: Record<string, unknown>;
  created_at: string | null;
  applied_at: string | null;
};

type DecisionVotesTally = {
  approve: number;
  deny: number;
  abstain: number;
};

async function loadDecision(
  id: string,
): Promise<
  | { kind: "ok"; data: DecisionDetail }
  | { kind: "forbidden" }
  | { kind: "not_found" }
  | { kind: "error" }
> {
  try {
    const data = await serverFetch<DecisionDetail>(
      `/api/decisions/${encodeURIComponent(id)}`,
    );
    return { kind: "ok", data };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 403) return { kind: "forbidden" };
      if (err.status === 404) return { kind: "not_found" };
    }
    return { kind: "error" };
  }
}

async function loadVotesBestEffort(
  id: string,
): Promise<DecisionVotesTally | null> {
  try {
    const r = await serverFetch<{ tally?: DecisionVotesTally }>(
      `/api/decisions/${encodeURIComponent(id)}/votes`,
    );
    return r.tally ?? null;
  } catch {
    // Best-effort — vote tally is optional context, not load-bearing.
    return null;
  }
}

const OUTCOME_TONE: Record<string, "neutral" | "accent" | "ok" | "amber" | "danger"> = {
  ok: "ok",
  advisory: "amber",
  partial: "amber",
  failed: "danger",
};

export default async function DecisionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/decisions/${id}`);
  const t = await getTranslations("shellV062.decisions.detail");
  const result = await loadDecision(id);

  if (result.kind === "forbidden") {
    return <Shell><EmptyState>{t("forbidden")}</EmptyState></Shell>;
  }
  if (result.kind === "not_found") {
    return <Shell><EmptyState>{t("notFound", { id })}</EmptyState></Shell>;
  }
  if (result.kind === "error") {
    return <Shell><EmptyState>{t("loadError")}</EmptyState></Shell>;
  }

  const dec = result.data;
  const tally = await loadVotesBestEffort(id);
  const outcomeTone =
    dec.apply_outcome && OUTCOME_TONE[dec.apply_outcome]
      ? OUTCOME_TONE[dec.apply_outcome]
      : "neutral";

  // Title heuristic: rationale's first line. Falls back to custom_text
  // or the bare id so the page never renders an empty header.
  const title =
    (dec.rationale && firstLine(dec.rationale)) ||
    (dec.custom_text && firstLine(dec.custom_text)) ||
    dec.id.slice(0, 8);

  return (
    <Shell>
      <PageHeader
        kicker="Decision"
        title={title}
        subtitle={t("subtitle")}
        right={
          dec.apply_outcome ? (
            <Tag tone={outcomeTone}>{dec.apply_outcome}</Tag>
          ) : undefined
        }
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <Card title={t("rationaleTitle")}>
          {dec.rationale ? (
            <Text as="p" variant="body" style={{ whiteSpace: "pre-wrap" }}>
              {dec.rationale}
            </Text>
          ) : (
            <EmptyState>{t("noRationale")}</EmptyState>
          )}
          {dec.custom_text ? (
            <div style={{ marginTop: 12 }}>
              <Text variant="caption" muted>
                {t("customTextLabel")}
              </Text>
              <Text
                as="p"
                variant="body"
                style={{ whiteSpace: "pre-wrap", marginTop: 4 }}
              >
                {dec.custom_text}
              </Text>
            </div>
          ) : null}
        </Card>

        <Card title={t("metaTitle")}>
          <Meta label={t("meta.id")} value={dec.id} />
          {dec.project_id ? (
            <Meta
              label={t("meta.scope")}
              value={
                <Link
                  href={`/scopes/${encodeURIComponent(dec.project_id)}`}
                  style={{ color: "var(--wg-accent)" }}
                >
                  {dec.project_id.slice(0, 8)} →
                </Link>
              }
            />
          ) : (
            <Meta label={t("meta.scope")} value="—" />
          )}
          <Meta
            label={t("meta.resolver")}
            value={
              dec.resolver_id ? `user:${dec.resolver_id.slice(0, 8)}` : "—"
            }
          />
          <Meta
            label={t("meta.option")}
            value={
              dec.option_index !== null && dec.option_index !== undefined
                ? `#${dec.option_index}`
                : t("meta.customOption")
            }
          />
          {dec.conflict_id ? (
            <Meta label={t("meta.conflict")} value={dec.conflict_id} />
          ) : null}
          <Meta label={t("meta.created")} value={dec.created_at || "—"} />
          <Meta label={t("meta.applied")} value={dec.applied_at || "—"} />
          {tally ? (
            <Meta
              label={t("meta.votes")}
              value={`${tally.approve}/${tally.deny}/${tally.abstain}`}
            />
          ) : null}
        </Card>
      </div>

      <Card variant="sunk" style={{ marginTop: 16 }}>
        <Text variant="caption" muted>
          {t("notWired")}
        </Text>
      </Card>
    </Shell>
  );
}

function firstLine(s: string): string {
  const idx = s.indexOf("\n");
  const head = idx >= 0 ? s.slice(0, idx) : s;
  return head.length > 160 ? head.slice(0, 160) + "…" : head;
}

function Meta({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        marginBottom: 6,
        alignItems: "baseline",
      }}
    >
      <Text
        variant="caption"
        muted
        style={{
          minWidth: 90,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </Text>
      <Text variant="body" as="span">
        {value}
      </Text>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      {children}
    </main>
  );
}
