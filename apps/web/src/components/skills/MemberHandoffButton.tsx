"use client";

// Small client island rendered inside an otherwise-server MemberCard.
// Owns the modal open/close state and hands the departing + candidate
// cards through to HandoffDialog.

import { useState } from "react";
import { useTranslations } from "next-intl";

import type { SkillAtlasMemberCard } from "@/lib/api";
import { HandoffDialog } from "./HandoffDialog";

type Props = {
  projectId: string;
  departingMember: SkillAtlasMemberCard;
  candidates: SkillAtlasMemberCard[];
};

export function MemberHandoffButton({
  projectId,
  departingMember,
  candidates,
}: Props) {
  const t = useTranslations("skillAtlas.card");
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        style={{
          padding: "3px 10px",
          background: "transparent",
          color: "var(--wg-accent)",
          border: "1px solid var(--wg-accent)",
          borderRadius: 12,
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          cursor: "pointer",
        }}
      >
        {t("handoffButton")}
      </button>
      {open && (
        <HandoffDialog
          projectId={projectId}
          departingMember={departingMember}
          candidates={candidates}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
