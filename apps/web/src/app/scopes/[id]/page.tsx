// /scopes/[id] — scope (project) read-only X-ray.
//
// Phase RW-6 (2026-05-13): the Phase E.1 placeholder is replaced
// with a real read-only body sourced from the live
// GET /api/scopes/:id endpoint added in this slice. The page renders
// the scope's title, role, tier, and full member roster, plus
// scoped deep links into the four primary surfaces that filter by
// scope (Conversations, Flow Center, Tasks, Documents).
//
// No mutation. No fabricated lineage. If the scope id doesn't
// resolve (404) or the viewer isn't a member (403), an honest
// not-found / forbidden state renders.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Card, EmptyState, PageHeader, Tag, Text } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

type ScopeMember = {
  user_id: string;
  username: string | null;
  display_name: string | null;
  role: string | null;
  license_tier?: string | null;
  skill_tags?: string[];
};

type ScopeDetail = {
  id: string;
  title: string;
  role: string;
  tier: "personal" | "cell" | "department" | "enterprise";
  members: ScopeMember[];
};

async function loadScope(
  id: string,
): Promise<{ kind: "ok"; data: ScopeDetail } | { kind: "forbidden" } | { kind: "not_found" } | { kind: "error" }> {
  try {
    const data = await serverFetch<ScopeDetail>(
      `/api/scopes/${encodeURIComponent(id)}`,
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

export default async function ScopeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/scopes/${id}`);
  const t = await getTranslations("shellV062.scopes.detail");
  const result = await loadScope(id);

  if (result.kind === "forbidden") {
    return <Shell><EmptyState>{t("forbidden")}</EmptyState></Shell>;
  }
  if (result.kind === "not_found") {
    return <Shell><EmptyState>{t("notFound", { id })}</EmptyState></Shell>;
  }
  if (result.kind === "error") {
    return <Shell><EmptyState>{t("loadError")}</EmptyState></Shell>;
  }

  const scope = result.data;

  return (
    <Shell>
      <PageHeader
        kicker="Scope"
        title={scope.title}
        subtitle={t("subtitle")}
        right={
          <div style={{ display: "flex", gap: 8 }}>
            <Tag tone="neutral">{scope.tier}</Tag>
            <Tag tone="accent">{scope.role}</Tag>
          </div>
        }
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <Card title={t("membersTitle", { count: scope.members.length })}>
          {scope.members.length === 0 ? (
            <EmptyState>{t("noMembers")}</EmptyState>
          ) : (
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: 0,
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              {scope.members.map((m) => (
                <li key={m.user_id}>
                  <Text variant="body">
                    {m.display_name || m.username || m.user_id.slice(0, 8)}
                  </Text>
                  {m.role && m.role !== "member" ? (
                    <Text variant="caption" muted>
                      {" "}· {m.role}
                    </Text>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={t("surfacesTitle")}>
          <ul
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <SurfaceLink
              href={`/conversations?scope_id=${encodeURIComponent(scope.id)}`}
              label={t("surfaces.conversations")}
            />
            <SurfaceLink
              href={`/flow-center?scope_id=${encodeURIComponent(scope.id)}`}
              label={t("surfaces.flowCenter")}
            />
            <SurfaceLink
              href={`/tasks?scope_id=${encodeURIComponent(scope.id)}`}
              label={t("surfaces.tasks")}
            />
            <SurfaceLink
              href={`/docs?scope_id=${encodeURIComponent(scope.id)}`}
              label={t("surfaces.docs")}
            />
          </ul>
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

function SurfaceLink({ href, label }: { href: string; label: string }) {
  return (
    <li>
      <Link
        href={href}
        style={{
          color: "var(--wg-accent)",
          textDecoration: "none",
          fontFamily: "var(--wg-font-sans)",
          fontSize: "var(--wg-fs-body)",
        }}
      >
        {label} →
      </Link>
    </li>
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
