"use client";

// SignalsPanel — per-signal Accept buttons for a metabolized transcript.
//
// Extracted signals live on the MeetingTranscriptRow as a JSON blob
// with four arrays: decisions / tasks / risks / stances. Stances are
// informational only (they track WHO holds WHAT position, not a thing
// to accept). The other three kinds each have an Accept button that
// POSTs to the accept endpoint and routes through the canonical ORM
// creation paths server-side.
//
// After accept, the bucket item is locally marked so the UI greys out
// the button and renders the new entity id for provenance. A full
// page refresh (router.refresh) picks up the server-authoritative
// state without a second round-trip.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Card, EmptyState, Text } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

type SignalKind = "decision" | "task" | "risk";

interface Decision {
  text: string;
  rationale?: string;
  _accepted_entity_id?: string;
}
interface Task {
  title: string;
  description?: string;
  suggested_owner_hint?: string;
  _accepted_entity_id?: string;
}
interface Risk {
  title: string;
  severity?: string;
  content?: string;
  _accepted_entity_id?: string;
}
interface Stance {
  participant_hint: string;
  topic: string;
  stance: string;
}

export interface ExtractedSignals {
  decisions?: Decision[];
  tasks?: Task[];
  risks?: Risk[];
  stances?: Stance[];
}

export function SignalsPanel({
  projectId,
  transcriptId,
  signals,
  status,
}: {
  projectId: string;
  transcriptId: string;
  signals: ExtractedSignals;
  status: string;
}) {
  const t = useTranslations("meeting");
  const router = useRouter();
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [locallyAccepted, setLocallyAccepted] = useState<Set<string>>(
    new Set(),
  );

  async function accept(kind: SignalKind, idx: number) {
    const key = `${kind}:${idx}`;
    setBusyKey(key);
    setErrorKey(null);
    try {
      await api(
        `/api/projects/${projectId}/meetings/${transcriptId}/signals/${kind}/${idx}/accept`,
        { method: "POST", body: {} },
      );
      setLocallyAccepted((prev) => {
        const next = new Set(prev);
        next.add(key);
        return next;
      });
      router.refresh();
    } catch (err) {
      setErrorKey(
        err instanceof ApiError
          ? `${key}:${err.status}`
          : `${key}:network`,
      );
    } finally {
      setBusyKey(null);
    }
  }

  if (status === "pending") {
    return (
      <Card title={t("signalsHeading")}>
        <EmptyState>{t("signalsPending")}</EmptyState>
      </Card>
    );
  }
  if (status === "failed") {
    return (
      <Card accent="terracotta" title={t("signalsHeading")}>
        <Text variant="caption">{t("signalsFailed")}</Text>
      </Card>
    );
  }

  const decisions = signals.decisions ?? [];
  const tasks = signals.tasks ?? [];
  const risks = signals.risks ?? [];
  const stances = signals.stances ?? [];
  const total = decisions.length + tasks.length + risks.length + stances.length;

  if (total === 0) {
    return (
      <Card title={t("signalsHeading")}>
        <EmptyState>{t("signalsEmpty")}</EmptyState>
      </Card>
    );
  }

  return (
    <Card title={t("signalsHeading")} subtitle={String(total)}>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <SignalGroup
          heading={t("groupDecisions")}
          items={decisions.map((d, idx) => {
            const key = `decision:${idx}`;
            const accepted =
              !!d._accepted_entity_id || locallyAccepted.has(key);
            return (
              <SignalRow
                key={key}
                primary={d.text}
                secondary={d.rationale}
                accepted={accepted}
                busy={busyKey === key}
                onAccept={() => accept("decision", idx)}
                acceptLabel={t("acceptDecision")}
                acceptedLabel={t("accepted")}
                errorHint={errorKey?.startsWith(key) ? errorKey : null}
              />
            );
          })}
          emptyLabel={t("groupEmptyDecisions")}
        />
        <SignalGroup
          heading={t("groupTasks")}
          items={tasks.map((task, idx) => {
            const key = `task:${idx}`;
            const accepted =
              !!task._accepted_entity_id || locallyAccepted.has(key);
            const secondary = [
              task.suggested_owner_hint
                ? `${t("ownerHint")}: ${task.suggested_owner_hint}`
                : null,
              task.description,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <SignalRow
                key={key}
                primary={task.title}
                secondary={secondary}
                accepted={accepted}
                busy={busyKey === key}
                onAccept={() => accept("task", idx)}
                acceptLabel={t("acceptTask")}
                acceptedLabel={t("accepted")}
                errorHint={errorKey?.startsWith(key) ? errorKey : null}
              />
            );
          })}
          emptyLabel={t("groupEmptyTasks")}
        />
        <SignalGroup
          heading={t("groupRisks")}
          items={risks.map((risk, idx) => {
            const key = `risk:${idx}`;
            const accepted =
              !!risk._accepted_entity_id || locallyAccepted.has(key);
            const secondary = [
              risk.severity ? `${t("severity")}: ${risk.severity}` : null,
              risk.content,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <SignalRow
                key={key}
                primary={risk.title}
                secondary={secondary}
                accepted={accepted}
                busy={busyKey === key}
                onAccept={() => accept("risk", idx)}
                acceptLabel={t("acceptRisk")}
                acceptedLabel={t("accepted")}
                errorHint={errorKey?.startsWith(key) ? errorKey : null}
              />
            );
          })}
          emptyLabel={t("groupEmptyRisks")}
        />
        {stances.length > 0 ? (
          <section>
            <Text variant="label" muted style={{ marginBottom: 6 }}>
              {t("groupStances")}
            </Text>
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: 0,
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              {stances.map((stance, idx) => (
                <li key={idx}>
                  <Text variant="body">
                    <strong>{stance.participant_hint}</strong>{" "}
                    <em>({stance.topic})</em> — {stance.stance}
                  </Text>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </Card>
  );
}

function SignalGroup({
  heading,
  items,
  emptyLabel,
}: {
  heading: string;
  items: React.ReactNode[];
  emptyLabel: string;
}) {
  return (
    <section>
      <Text variant="label" muted style={{ marginBottom: 6 }}>
        {heading}
      </Text>
      {items.length === 0 ? (
        <Text variant="caption" muted>
          {emptyLabel}
        </Text>
      ) : (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          {items.map((item, idx) => (
            <li key={idx}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SignalRow({
  primary,
  secondary,
  accepted,
  busy,
  onAccept,
  acceptLabel,
  acceptedLabel,
  errorHint,
}: {
  primary: string;
  secondary?: string;
  accepted: boolean;
  busy: boolean;
  onAccept: () => void;
  acceptLabel: string;
  acceptedLabel: string;
  errorHint: string | null;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 12,
        padding: "8px 10px",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface-raised)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
        <Text variant="body">{primary}</Text>
        {secondary ? (
          <Text variant="caption" muted>
            {secondary}
          </Text>
        ) : null}
        {errorHint ? (
          <Text variant="caption" style={{ color: "var(--wg-accent)" }}>
            {errorHint}
          </Text>
        ) : null}
      </div>
      <Button
        size="sm"
        variant={accepted ? "ghost" : "primary"}
        onClick={onAccept}
        disabled={accepted || busy}
      >
        {accepted ? acceptedLabel : acceptLabel}
      </Button>
    </div>
  );
}
