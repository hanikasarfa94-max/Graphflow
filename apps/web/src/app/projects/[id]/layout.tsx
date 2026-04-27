import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Phase Q — project layout is deliberately minimal.
//
// Navigation (Home / projects / team room / status / KB / renders / DMs)
// lives in the global AppSidebar. Notifications live in the sidebar's
// routed-inbox badge. The old in-page breadcrumb + h1 + sub-nav ate
// ~175px at the top of every chat view; gone.
//
// F.17 transparent-passthrough pass: the layout used to also render
// the "tasks · deliverables · v" metadata strip and cap width at
// 1200px. On chat surfaces (`/projects/[id]`, `/team`) the metadata
// was meaningless chrome and the cap choked the chat. Other pages
// (status, kb, org, renders, skills) already set their own
// max-width inside their own `<main>`, so the cap was redundant
// there. Layout is now a thin auth gate; pages own their width.
export default async function ProjectLayout({
  params,
  children,
}: {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}`);
  return <>{children}</>;
}
