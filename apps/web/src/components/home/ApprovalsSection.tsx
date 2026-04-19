import { getTranslations } from "next-intl/server";

import { SectionHeader } from "./SectionHeader";

// Phase F §3 — placeholder section for gated admin approvals. The backend
// has no "approver role" primitive yet, so in v1 we render this only for
// users who hold an admin-tier role on at least one project (via
// ProjectMemberRow.role === 'admin') and the body is an explicit v2 note.
// Keeps the UX affordance visible for the demo even though nothing routes
// here yet. Future work: a formal gated-decision signal-chain variant.
export async function ApprovalsSection() {
  const t = await getTranslations();
  return (
    <section style={{ marginBottom: 40 }} aria-labelledby="home-approvals">
      <SectionHeader title={t("home.approvals.title")} subdued />
      <div
        style={{
          padding: 16,
          border: "1px dashed var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          color: "var(--wg-ink-faint)",
          fontSize: 13,
          fontStyle: "italic",
        }}
      >
        {t("home.approvals.placeholderNote")}
      </div>
    </section>
  );
}
