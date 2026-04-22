"use client";

// OnboardingOverlay — Phase 1.B ambient Day-1 walkthrough.
//
// Renders a full-viewport modal-style overlay on the first visit to
// `/projects/[id]`. The server fetches the walkthrough state + script;
// this client component runs the progress UI, keyboard shortcuts, and
// the POSTs that advance or dismiss.
//
// Gating: the parent page only mounts this when the server-side state
// says walkthrough_completed_at is null AND dismissed is false. So we
// don't repeat that check here — if this component mounts, we show it.
//
// Keyboard:
//   Esc       → dismiss
//   → / Enter → advance (or complete on the final step)
//
// Citations use the shared CitedClaimList so chips deep-link to
// /projects/[id]/nodes/[nodeId] — the exact same behaviour as in the
// personal stream.

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { CitedClaimList } from "@/components/stream/CitedClaimList";
import { Button, Heading, Text } from "@/components/ui";
import {
  type OnboardingCheckpoint,
  type OnboardingSection,
  type OnboardingState,
  type OnboardingWalkthrough,
  postOnboardingCheckpoint,
  postOnboardingDismiss,
} from "@/lib/api";

const SECTION_ORDER: OnboardingSection["kind"][] = [
  "vision",
  "decisions",
  "teammates",
  "your_tasks",
  "open_risks",
];

const CHECKPOINT_BY_INDEX: OnboardingCheckpoint[] = [
  "vision",
  "decisions",
  "teammates",
  "your_tasks",
  "open_risks",
];

type Props = {
  projectId: string;
  walkthrough: OnboardingWalkthrough;
  initialState: OnboardingState;
};

export function OnboardingOverlay({
  projectId,
  walkthrough,
  initialState,
}: Props) {
  const t = useTranslations("onboarding");
  const tSections = useTranslations("onboarding.sections");

  const [visible, setVisible] = useState<boolean>(
    !initialState.walkthrough_completed_at && !initialState.dismissed,
  );
  const [stepIndex, setStepIndex] = useState<number>(() =>
    startStepFromCheckpoint(initialState.last_checkpoint),
  );
  const [busy, setBusy] = useState<boolean>(false);

  // Map the walkthrough payload to the canonical 5-section order. If a
  // section is missing from the payload we render a placeholder — this
  // should not happen in practice but keeps the UI resilient.
  const sections: OnboardingSection[] = SECTION_ORDER.map(
    (kind) =>
      walkthrough.sections.find((s) => s.kind === kind) ?? {
        kind,
        title: kind,
        body_md: "",
        claims: [],
      },
  );

  const total = sections.length;
  const current = sections[stepIndex];
  const isLast = stepIndex >= total - 1;

  const advance = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (isLast) {
        await postOnboardingCheckpoint(projectId, "completed");
        setVisible(false);
      } else {
        const nextIdx = stepIndex + 1;
        await postOnboardingCheckpoint(
          projectId,
          CHECKPOINT_BY_INDEX[stepIndex],
        );
        setStepIndex(nextIdx);
      }
    } finally {
      setBusy(false);
    }
  }, [busy, isLast, projectId, stepIndex]);

  const dismiss = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      await postOnboardingDismiss(projectId);
      setVisible(false);
    } finally {
      setBusy(false);
    }
  }, [busy, projectId]);

  useEffect(() => {
    if (!visible) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        dismiss();
      } else if (e.key === "Enter" || e.key === "ArrowRight") {
        e.preventDefault();
        advance();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, advance, dismiss]);

  if (!visible) return null;

  const tier = walkthrough.license_tier || "full";
  const restricted = tier !== "full";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      data-testid="onboarding-overlay"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(24, 20, 14, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 24,
      }}
    >
      <div
        style={{
          width: "min(720px, 100%)",
          maxHeight: "calc(100vh - 48px)",
          overflow: "auto",
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          boxShadow: "0 16px 48px rgba(0, 0, 0, 0.18)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header
          style={{
            padding: "20px 24px 12px",
            borderBottom: "1px solid var(--wg-line-soft)",
          }}
        >
          <Text
            as="div"
            variant="label"
            muted
            style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
          >
            {t("progress", { current: stepIndex + 1, total })}
          </Text>
          <Heading
            level={2}
            id="onboarding-title"
            style={{ margin: "6px 0 2px" }}
          >
            {t("overlayTitle")}
          </Heading>
          <Text as="p" variant="body" muted style={{ margin: 0 }}>
            {t("subtitle")}
          </Text>
          {restricted ? (
            <Text
              as="p"
              variant="label"
              muted
              style={{
                margin: "8px 0 0",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t("restrictedNotice", { tier })}
            </Text>
          ) : null}
        </header>

        <div
          style={{ padding: "20px 24px" }}
          data-testid="onboarding-section"
          data-section-kind={current.kind}
        >
          <Heading level={3} style={{ margin: "0 0 8px" }}>
            {tSections(current.kind)}
          </Heading>
          {current.body_md ? (
            <Text
              as="pre"
              variant="body"
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                margin: 0,
                fontFamily: "var(--wg-font-sans)",
              }}
            >
              {current.body_md}
            </Text>
          ) : (
            <Text as="p" variant="body" muted>
              {t("emptySection")}
            </Text>
          )}
          {current.claims && current.claims.length > 0 ? (
            <div style={{ marginTop: 12 }}>
              <CitedClaimList
                projectId={projectId}
                claims={current.claims}
              />
            </div>
          ) : null}
        </div>

        <footer
          style={{
            padding: "12px 24px 20px",
            borderTop: "1px solid var(--wg-line-soft)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <Button
            variant="link"
            size="sm"
            onClick={dismiss}
            disabled={busy}
            data-testid="onboarding-skip"
          >
            {t("skip")}
          </Button>
          <div style={{ display: "flex", gap: 8 }}>
            <ProgressDots total={total} current={stepIndex} />
            <Button
              variant="primary"
              onClick={advance}
              disabled={busy}
              data-testid="onboarding-advance"
            >
              {isLast ? t("done") : t("next")}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}

function ProgressDots({
  total,
  current,
}: {
  total: number;
  current: number;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        paddingRight: 8,
      }}
      aria-hidden
    >
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            background:
              i <= current ? "var(--wg-accent)" : "var(--wg-line)",
          }}
        />
      ))}
    </div>
  );
}

function startStepFromCheckpoint(
  checkpoint: OnboardingCheckpoint,
): number {
  switch (checkpoint) {
    case "vision":
      return 1;
    case "decisions":
      return 2;
    case "teammates":
      return 3;
    case "your_tasks":
      return 4;
    case "open_risks":
      return 4; // last section reached — keep user on it until they
    // click "Done"
    case "completed":
      return 4;
    case "not_started":
    default:
      return 0;
  }
}
