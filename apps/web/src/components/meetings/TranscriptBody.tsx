"use client";

// TranscriptBody — collapsible display of the stored transcript text.
// Shows the first 300 chars by default with an expand/collapse toggle;
// monospace font so speaker labels + timestamps (if preserved) stay
// readable. Respects `var(--wg-font-mono)`.

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Text } from "@/components/ui";

const COLLAPSED_CHARS = 300;

export function TranscriptBody({ text }: { text: string }) {
  const t = useTranslations("meeting");
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > COLLAPSED_CHARS;
  const shown = !expanded && isLong ? text.slice(0, COLLAPSED_CHARS) + "…" : text;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <pre
        style={{
          margin: 0,
          padding: 12,
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
          lineHeight: 1.5,
          color: "var(--wg-ink)",
          background: "var(--wg-surface-sunk)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          maxHeight: expanded ? "none" : 240,
          overflow: "auto",
        }}
      >
        {shown}
      </pre>
      {isLong ? (
        <div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? t("collapseTranscript") : t("expandTranscript")}
          </Button>
        </div>
      ) : (
        <Text variant="caption" muted>
          {text.length} {t("chars")}
        </Text>
      )}
    </div>
  );
}
