import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DMStream } from "@/components/stream/DMStream";
import type { StreamMember } from "@/components/stream/types";
import type { StreamSummary } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Phase H — the 1:1 DM surface. Also the canonical /streams/[id] route;
// when the id resolves to a project-type stream we redirect to the
// project URL so project streams keep their existing canonical path.
//
// Data flow (v1):
//   * GET /api/streams → filter for the requested id (backend has no
//     /api/streams/{id} singleton yet, but the list is already
//     authorization-scoped to the caller so this is correct).
//   * On miss: show a not-found notice — either the stream doesn't exist
//     or the caller isn't a member.
//   * On project-type: redirect to /projects/{project_id}.
//   * On dm-type: hand off to <DMStream>, which renders header +
//     timeline + composer.
export default async function StreamPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/streams/${id}`);

  let list: { streams: StreamSummary[] } | null = null;
  try {
    list = await serverFetch<{ streams: StreamSummary[] }>(`/api/streams`);
  } catch {
    list = null;
  }

  const stream = list?.streams.find((s) => s.id === id) ?? null;

  if (stream?.type === "project" && stream.project_id) {
    redirect(`/projects/${stream.project_id}`);
  }

  const tDm = await getTranslations("dm");

  if (!stream) {
    return (
      <main style={{ maxWidth: 720, margin: "40px auto", padding: "0 24px" }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, marginBottom: 8 }}>
          {tDm("title")}
        </h1>
        <p
          style={{
            color: "var(--wg-ink-soft)",
            fontSize: 14,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {tDm("notFound")}
        </p>
      </main>
    );
  }

  const members: StreamMember[] = stream.members.map((m) => ({
    user_id: m.user_id,
    username: m.username,
    display_name: m.display_name,
    role_in_stream: m.role_in_stream,
  }));

  return (
    <main style={{ maxWidth: 1000, margin: "0 auto", padding: "32px 24px" }}>
      <DMStream
        streamId={stream.id}
        currentUserId={user.id}
        members={members}
      />
    </main>
  );
}
