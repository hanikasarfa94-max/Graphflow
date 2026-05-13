// /nodes/[id] — generic Proof Page wrapper.
//
// Phase RW-6 (2026-05-13): the Phase E.1 placeholder is replaced
// with a real resolver that probes the live endpoints in priority
// order and redirects to the kind-specific route on hit:
//
//   1. GET /api/kb-items/:id   → /kb-items/:id
//   2. GET /api/decisions/:id  → /decisions/:id
//
// If neither resolves, an honest "unresolved" body renders. We do
// NOT invent lineage or evidence for unknown ids. Graph-internal
// nodes (goals / deliverables / constraints / risks) aren't
// queryable by id alone today — they live inside project state —
// so they show as unresolved here and the user gets pointed at
// /scopes/:id to navigate to them via project context.
//
// Two parallel fetches per page load is acceptable for an audit-
// scoped surface that's not on the hot path. If the proof page
// becomes hot, a single backend resolver endpoint replaces this.

import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { Card, EmptyState, PageHeader, Tag, Text } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

type ResolveResult =
  | { kind: "kb_item" }
  | { kind: "decision" }
  | { kind: "unresolved" }
  | { kind: "forbidden" };

async function resolveKind(id: string): Promise<ResolveResult> {
  // Probe both in parallel — both endpoints return 404 quickly when
  // they don't recognize the id, and 403 when the viewer can't see
  // it (still a hit on this id; redirect so the destination page
  // renders the bilingual 403 state).
  const [kbHit, decHit] = await Promise.allSettled([
    probe(`/api/kb-items/${encodeURIComponent(id)}`),
    probe(`/api/decisions/${encodeURIComponent(id)}`),
  ]);

  const kb = kbHit.status === "fulfilled" ? kbHit.value : "miss";
  const dec = decHit.status === "fulfilled" ? decHit.value : "miss";

  // Hit > forbidden > miss. If a viewer can see a kb-item version
  // of an id, that wins; falls back to decision; otherwise honest
  // unresolved.
  if (kb === "ok") return { kind: "kb_item" };
  if (dec === "ok") return { kind: "decision" };
  if (kb === "forbidden") return { kind: "forbidden" };
  if (dec === "forbidden") return { kind: "forbidden" };
  return { kind: "unresolved" };
}

async function probe(path: string): Promise<"ok" | "forbidden" | "miss"> {
  try {
    await serverFetch(path);
    return "ok";
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 403) return "forbidden";
      // 404 + 400 + 500 all fall to "miss" — the resolver doesn't
      // care about the difference, only "did this id name a thing
      // the viewer can read." Other handlers surface specific
      // errors on the kind-specific destination page.
      return "miss";
    }
    return "miss";
  }
}

export default async function NodeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/nodes/${id}`);
  const t = await getTranslations("shellV062.nodes.detail");
  const resolved = await resolveKind(id);

  if (resolved.kind === "kb_item") {
    redirect(`/kb-items/${encodeURIComponent(id)}`);
  }
  if (resolved.kind === "decision") {
    redirect(`/decisions/${encodeURIComponent(id)}`);
  }

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Node"
        title={t("title")}
        subtitle={t("subtitle")}
        right={<Tag tone="amber">{t("unresolvedTag")}</Tag>}
      />

      <Card>
        <EmptyState>
          {resolved.kind === "forbidden"
            ? t("forbidden", { id })
            : t("unresolvedBody", { id })}
        </EmptyState>
      </Card>

      <Card variant="sunk" style={{ marginTop: 16 }}>
        <Text variant="caption" muted>
          {t("hint")}
        </Text>
      </Card>
    </main>
  );
}
