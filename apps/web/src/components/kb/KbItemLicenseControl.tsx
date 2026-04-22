"use client";

// Owner-only per-item license override dropdown.
//
// Rendered on the KB item detail page's sidebar when the viewer is a
// project owner. Reads the current override via /kb/tree on mount
// (cheap — the tree is shared across the kb surface anyway) and
// writes via PUT /kb/items/{id}/license.
//
// Non-owners never see this component; the page composition gates
// on role before rendering.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Text } from "@/components/ui";
import {
  getKbTree,
  type LicenseTier,
  setKbItemLicense,
} from "@/lib/api";

type Choice = "inherit" | LicenseTier;

export function KbItemLicenseControl({
  projectId,
  itemId,
}: {
  projectId: string;
  itemId: string;
}) {
  const t = useTranslations();
  const [current, setCurrent] = useState<Choice>("inherit");
  const [pending, setPending] = useState<Choice>("inherit");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const tree = await getKbTree(projectId);
        if (cancelled) return;
        const match = tree.items.find((i) => i.id === itemId);
        const value: Choice = match?.license_tier_override ?? "inherit";
        setCurrent(value);
        setPending(value);
      } catch (err) {
        setError(err instanceof Error ? err.message : "failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, itemId]);

  const dirty = pending !== current;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await setKbItemLicense(
        projectId,
        itemId,
        pending === "inherit" ? null : pending,
      );
      setCurrent(pending);
    } catch (err) {
      setError(err instanceof Error ? err.message : "failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      style={{
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "#fff",
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <Text variant="caption" muted>
        {t("kb.license.label")}
      </Text>
      <select
        value={pending}
        onChange={(e) => setPending(e.target.value as Choice)}
        disabled={saving}
        aria-label={t("kb.license.label")}
        style={{
          width: "100%",
          padding: "6px 8px",
          fontSize: 13,
          fontFamily: "inherit",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          background: "#fff",
          color: "var(--wg-ink)",
        }}
      >
        <option value="inherit">{t("kb.license.inherit")}</option>
        <option value="full">{t("kb.license.tier.full")}</option>
        <option value="task_scoped">
          {t("kb.license.tier.task_scoped")}
        </option>
        <option value="observer">
          {t("kb.license.tier.observer")}
        </option>
      </select>
      <Text variant="caption" muted>
        {t("kb.license.help")}
      </Text>
      {dirty ? (
        <div style={{ display: "flex", gap: 6 }}>
          <Button
            size="sm"
            variant="primary"
            onClick={save}
            disabled={saving}
          >
            {saving
              ? t("kb.license.saving")
              : t("kb.license.save")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setPending(current)}
            disabled={saving}
          >
            {t("kb.license.cancel")}
          </Button>
        </div>
      ) : null}
      {error ? (
        <Text variant="caption" style={{ color: "var(--wg-accent)" }}>
          {error}
        </Text>
      ) : null}
    </section>
  );
}
