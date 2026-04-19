// /projects/[id]/renders/[slug] — Phase R rendered artifact page.
//
// Slug contract:
//   - `postmortem`          → project-wide postmortem render
//   - `handoff:<user_id>`   → that user's handoff render
//
// This server component:
//   1) validates the slug
//   2) fetches the render (server-side, forwards auth cookie)
//   3) also fetches /state so we have the real decision id set to
//      ground `**D-<id>**` citations into /nodes links
//   4) renders <RenderView> (client component) with the initial data
//
// The render endpoint caches first-gen results on the backend, so
// navigating to this page for the first time synchronously triggers the
// LLM call. Subsequent visits hit the cache until the user regenerates.

import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import type {
  HandoffRender,
  PostmortemRender,
  ProjectState,
} from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

import { RenderView } from "./RenderView";

export const dynamic = "force-dynamic";

type SlugKind =
  | { kind: "postmortem" }
  | { kind: "handoff"; userId: string }
  | { kind: "unknown" };

function parseSlug(raw: string): SlugKind {
  if (raw === "postmortem") return { kind: "postmortem" };
  if (raw.startsWith("handoff:")) {
    const userId = raw.slice("handoff:".length);
    if (!userId) return { kind: "unknown" };
    return { kind: "handoff", userId };
  }
  return { kind: "unknown" };
}

export default async function RenderedArtifactPage({
  params,
}: {
  params: Promise<{ id: string; slug: string }>;
}) {
  const { id, slug: rawSlug } = await params;
  const slug = decodeURIComponent(rawSlug);
  await requireUser(`/projects/${id}/renders/${rawSlug}`);
  const t = await getTranslations();

  const parsed = parseSlug(slug);
  if (parsed.kind === "unknown") {
    return (
      <main style={{ padding: 40, maxWidth: 720, margin: "0 auto" }}>
        <p style={{ color: "var(--wg-accent, #c03030)" }}>
          {t("render.unknownSlug")}
        </p>
      </main>
    );
  }

  // Fetch render + project state in parallel. On transport error we
  // surface a graceful message rather than 500ing the page.
  const renderPath =
    parsed.kind === "postmortem"
      ? `/api/projects/${id}/renders/postmortem`
      : `/api/projects/${id}/renders/handoff/${parsed.userId}`;

  let render: PostmortemRender | HandoffRender | null = null;
  let state: ProjectState | null = null;
  let errorMessage: string | null = null;

  try {
    const [rRes, sRes] = await Promise.all([
      serverFetch<PostmortemRender | HandoffRender>(renderPath),
      serverFetch<ProjectState>(`/api/projects/${id}/state`).catch(() => null),
    ]);
    render = rRes;
    state = sRes;
  } catch (err) {
    // 404 from backend = project/user not found; 403 = non-member
    // handled by layer above (requireUser throws on 401, not 403).
    errorMessage = err instanceof Error ? err.message : "failed";
  }

  if (!render) {
    return (
      <main style={{ padding: 40, maxWidth: 720, margin: "0 auto" }}>
        <h1 style={{ fontSize: 22 }}>
          {parsed.kind === "postmortem"
            ? t("render.postmortem.title")
            : t("render.handoff.title")}
        </h1>
        <p style={{ color: "var(--wg-accent, #c03030)" }}>
          {errorMessage ?? t("render.loadFailed")}
        </p>
      </main>
    );
  }

  const decisionIds = (state?.decisions ?? []).map((d) => d.id);

  return (
    <RenderView
      projectId={id}
      slug={slug}
      initial={render}
      decisionIds={decisionIds}
      isPostmortem={parsed.kind === "postmortem"}
    />
  );
}
