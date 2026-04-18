import { EventStream } from "./EventStream";

export const dynamic = "force-dynamic";

export default async function EventsTab({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <EventStream projectId={id} />;
}
