// /workspaces/[slug] — Phase T workspace (Studio / Enterprise) detail.
//
// Read-only diagnostic view + invite affordance. Owner/admin can invite;
// everyone sees member roster + attached projects. Drag-rebalance,
// scoped views, and detach-project are v2.

import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";
import type {
  WorkspaceDetail,
  WorkspaceMember,
} from "@/lib/api";

import { InviteToWorkspaceSection } from "@/components/workspace/InviteToWorkspaceSection";

export const dynamic = "force-dynamic";

export default async function WorkspaceDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  await requireUser(`/workspaces/${slug}`);
  const t = await getTranslations("workspace");

  let detail: WorkspaceDetail | null = null;
  let members: WorkspaceMember[] = [];
  try {
    detail = await serverFetch<WorkspaceDetail>(`/api/organizations/${slug}`);
    members = await serverFetch<WorkspaceMember[]>(
      `/api/organizations/${slug}/members`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    if (err instanceof ApiError && err.status === 403) {
      return (
        <main style={{ maxWidth: 720, margin: "60px auto", padding: "0 24px" }}>
          <h1 style={{ fontSize: 22, marginBottom: 12 }}>
            {t("forbidden.title")}
          </h1>
          <p style={{ color: "var(--wg-ink-soft)" }}>
            {t("forbidden.body")}
          </p>
        </main>
      );
    }
    throw err;
  }

  if (!detail) notFound();
  const canInvite = detail.role === "owner" || detail.role === "admin";

  return (
    <main
      style={{
        maxWidth: 980,
        margin: "0 auto",
        padding: "40px 24px 80px",
        fontFamily: "var(--wg-font-sans)",
      }}
    >
      <header style={{ marginBottom: 24 }}>
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            marginBottom: 4,
          }}
        >
          {t("eyebrow")}
        </div>
        <h1
          style={{
            fontSize: 28,
            fontWeight: 600,
            color: "var(--wg-ink)",
            margin: "0 0 6px",
          }}
        >
          {detail.name}
        </h1>
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          <span>@{detail.slug}</span>
          <RoleBadge role={detail.role} t={t} />
        </div>
        {detail.description ? (
          <p
            style={{
              marginTop: 12,
              fontSize: 14,
              color: "var(--wg-ink-soft)",
              maxWidth: 640,
              lineHeight: 1.5,
            }}
          >
            {detail.description}
          </p>
        ) : null}
      </header>

      {canInvite ? (
        <section style={{ marginBottom: 32 }}>
          <InviteToWorkspaceSection slug={slug} />
        </section>
      ) : null}

      <section style={{ marginBottom: 32 }}>
        <h2
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            marginBottom: 10,
          }}
        >
          {t("members.title", { count: members.length })}
        </h2>
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
          {members.map((m) => (
            <li
              key={m.user_id}
              data-testid="workspace-member"
              data-role={m.role}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 14px",
                background: "var(--wg-surface-raised)",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius-sm, 4px)",
              }}
            >
              <div
                aria-hidden
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: "var(--wg-line)",
                  color: "var(--wg-ink-soft)",
                  fontWeight: 600,
                  fontSize: 12,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                {(m.display_name || m.username || "?").charAt(0).toUpperCase()}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: "var(--wg-ink)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {m.display_name || m.username}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--wg-ink-soft)",
                    fontFamily: "var(--wg-font-mono)",
                  }}
                >
                  @{m.username}
                </div>
              </div>
              <RoleBadge role={m.role} t={t} />
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            marginBottom: 10,
          }}
        >
          {t("projects.title")}
        </h2>
        {detail.projects.length === 0 ? (
          <p
            style={{
              fontSize: 13,
              color: "var(--wg-ink-soft)",
              fontStyle: "italic",
            }}
          >
            {t("projects.empty")}
          </p>
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
            {detail.projects.map((p) => (
              <li key={p.id}>
                <Link
                  href={`/projects/${p.id}`}
                  style={{
                    display: "block",
                    padding: "10px 14px",
                    background: "var(--wg-surface-raised)",
                    border: "1px solid var(--wg-line)",
                    borderRadius: "var(--wg-radius-sm, 4px)",
                    color: "var(--wg-ink)",
                    textDecoration: "none",
                    fontSize: 14,
                  }}
                >
                  {p.title}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function RoleBadge({
  role,
  t,
}: {
  role: WorkspaceMember["role"];
  t: (key: string) => string;
}) {
  const colors: Record<string, { bg: string; fg: string }> = {
    owner: { bg: "var(--wg-accent-soft)", fg: "var(--wg-accent)" },
    admin: { bg: "var(--wg-amber-soft)", fg: "var(--wg-amber)" },
    member: { bg: "var(--wg-surface-sunk)", fg: "var(--wg-ink-soft)" },
    viewer: { bg: "var(--wg-surface-sunk)", fg: "var(--wg-ink-faint)" },
  };
  const c = colors[role] ?? colors.member;
  return (
    <span
      data-testid="workspace-role-badge"
      data-role={role}
      style={{
        padding: "2px 8px",
        background: c.bg,
        color: c.fg,
        borderRadius: 999,
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
      }}
    >
      {t(`roles.${role}`)}
    </span>
  );
}
