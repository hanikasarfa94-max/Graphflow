import { getTranslations } from "next-intl/server";

import { EmptyState, Panel } from "./Panel";

// v1 placeholder — git + doc membrane ingestion isn't wired yet. When the
// membrane ships, swap this list for real artifact rows (commits, PRs,
// external doc links) pulled from an ingestion table.
export async function ArtifactsPanel() {
  const t = await getTranslations();

  return (
    <Panel title={t("status.artifacts.title")}>
      <EmptyState>{t("status.artifacts.empty")}</EmptyState>
    </Panel>
  );
}
