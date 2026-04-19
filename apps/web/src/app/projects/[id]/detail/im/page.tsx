import { requireUser } from "@/lib/auth";

import { ChatPane } from "./ChatPane";

export const dynamic = "force-dynamic";

export default async function ImTab({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/projects/${id}/detail/im`);
  return <ChatPane projectId={id} currentUserId={user.id} />;
}
