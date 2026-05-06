"use client";

// M1.2 — KB memory repair actions on the detail page.
//
// Three states:
//   * status='archived'     → read-only banner ("Archived"). No
//     restore action yet — defer to a later slice.
//   * group + project-owner → Archive button (confirm + soft-archive).
//   * group + member        → Request archive button (reason prompt
//     → IMSuggestion for owner to accept).
//   * personal + item-owner → Archive button. Personal hard-delete is
//     also still allowed (DELETE /api/kb-items/{id}) but the audit
//     value of soft-archive is non-zero even for personal rows so we
//     surface only Archive here.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button, Text } from "@/components/ui";
import { archiveKbNote, requestArchiveKb } from "@/lib/api";

export function KbItemActions({
  itemId,
  scope,
  status,
  isProjectOwner,
  isItemOwner,
}: {
  itemId: string;
  // Loose types: KbItemDetail.scope/status are nullable on the wire
  // (ingest rows don't set scope). Render nothing when missing.
  scope: string | null | undefined;
  status: string | null | undefined;
  isProjectOwner: boolean;
  isItemOwner: boolean;
}) {
  if (!scope) return null;
  const t = useTranslations();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestSent, setRequestSent] = useState(false);

  if (status === "archived") {
    return (
      <div
        style={{
          padding: "10px 12px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          background: "var(--wg-paper-2, #f7f6f1)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
        }}
      >
        {t("kb.actions.archivedBadge")}
      </div>
    );
  }

  const canArchiveDirect =
    (scope === "group" && isProjectOwner) ||
    (scope === "personal" && isItemOwner);
  const canRequestArchive =
    scope === "group" && !isProjectOwner;

  if (!canArchiveDirect && !canRequestArchive) return null;

  const archive = async () => {
    if (!window.confirm(t("kb.actions.confirmArchive"))) return;
    setBusy(true);
    setError(null);
    try {
      await archiveKbNote(itemId);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "archive_failed");
      setBusy(false);
    }
  };

  const requestArchive = async () => {
    const reason = window.prompt(t("kb.actions.reasonPrompt"));
    if (!reason || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await requestArchiveKb(itemId, { reason: reason.trim() });
      setRequestSent(true);
      setBusy(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "request_failed");
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "10px 12px",
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      <Text variant="caption" muted>
        {t("kb.actions.kicker")}
      </Text>
      {canArchiveDirect ? (
        <Button onClick={archive} disabled={busy} variant="ghost" size="sm">
          {busy ? t("kb.actions.archiving") : t("kb.actions.archive")}
        </Button>
      ) : null}
      {canRequestArchive && !requestSent ? (
        <Button
          onClick={requestArchive}
          disabled={busy}
          variant="ghost"
          size="sm"
        >
          {busy ? t("kb.actions.requesting") : t("kb.actions.requestArchive")}
        </Button>
      ) : null}
      {requestSent ? (
        <Text variant="caption" muted>
          {t("kb.actions.requestSent")}
        </Text>
      ) : null}
      {error ? (
        <Text variant="caption" muted>
          {error}
        </Text>
      ) : null}
    </div>
  );
}
