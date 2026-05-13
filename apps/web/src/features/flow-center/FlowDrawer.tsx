"use client";

// FlowDrawer — body for `useDrawer().open({ type: 'flow_request', ... })`.
//
// RW-9 (2026-05-13). The earlier "not wired yet" empty state is gone
// for route packets — the drawer now fetches GET /api/flow-requests/:id
// on mount and renders real fields when the request loads. For packet
// kinds the backend cannot map to a respondable surface (kb_review,
// handoff, decision, manual_*), the drawer renders an honest non-
// respondable Card explaining the kind.
//
// Memory decoupling invariant: even when /respond returns success,
// the FE does NOT auto-open the memory review drawer. The response
// envelope carries `memory_candidate_prompt.actions == [review, skip,
// later]` and the user is responsible for opening the prompt drawer
// from MemoryPromptDrawer. RW-9 keeps the two pipelines fully
// separate.

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDrawer } from "@/components/shell/v062/DrawerHost";
import { Button, Card, EmptyState, Tag, Text } from "@/components/ui";
import { formatIso } from "@/lib/time";

import {
  fetchFlowRequest,
  postFlowRequestResponse,
  type FetchFlowRequestResult,
} from "./flowRequestActions";
import type {
  FlowParticipant,
  FlowRequestSingleton,
  FlowRequestSingletonResponse,
  FlowRequestRespondability,
} from "./types";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; payload: FlowRequestSingletonResponse }
  | { kind: "not_supported"; unsupportedKind?: string }
  | { kind: "not_found" }
  | { kind: "forbidden" }
  | { kind: "error" };

function classifyFetch(result: FetchFlowRequestResult): LoadState {
  if (result.ok) return { kind: "ready", payload: result.data };
  switch (result.error) {
    case "not_supported_yet":
      return { kind: "not_supported", unsupportedKind: result.unsupportedKind };
    case "not_found":
      return { kind: "not_found" };
    case "forbidden":
      return { kind: "forbidden" };
    default:
      return { kind: "error" };
  }
}

function nameFor(
  participants: Record<string, FlowParticipant>,
  user_id: string | null | undefined,
): string {
  if (!user_id) return "—";
  const p = participants[user_id];
  if (!p) return user_id.slice(0, 8);
  return p.display_name || p.username || user_id.slice(0, 8);
}

export function FlowDrawer({ flow_id }: { flow_id: string }) {
  const t = useTranslations("shellV062.flowDrawer");
  const drawer = useDrawer();
  const router = useRouter();

  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchFlowRequest(flow_id).then((res) => {
      if (cancelled) return;
      setState(classifyFetch(res));
    });
    return () => {
      cancelled = true;
    };
  }, [flow_id, tick]);

  if (state.kind === "loading") {
    return (
      <div style={{ padding: 12 }}>
        <Text variant="caption" muted>
          {t("loading")}
        </Text>
      </div>
    );
  }

  if (state.kind === "not_supported") {
    return <NotSupportedState kind={state.unsupportedKind} flow_id={flow_id} />;
  }

  if (state.kind === "not_found") {
    return <ErrorState message={t("notFound")} flow_id={flow_id} />;
  }

  if (state.kind === "forbidden") {
    return <ErrorState message={t("forbidden")} flow_id={flow_id} />;
  }

  if (state.kind === "error") {
    return (
      <ErrorState message={t("genericError")} flow_id={flow_id}>
        <Button size="sm" variant="ghost" onClick={refetch}>
          {t("retry")}
        </Button>
      </ErrorState>
    );
  }

  // state.kind === "ready"
  return (
    <ReadyBody
      payload={state.payload}
      onResponded={() => {
        // Refetch the singleton so the drawer reflects the new state
        // (status flipped to replied; respondability flipped to false
        // because already_replied). Refresh the parent page so the
        // Flow Center table re-renders with the new packet status.
        refetch();
        router.refresh();
      }}
      onClose={drawer.close}
    />
  );
}

// ── States ─────────────────────────────────────────────────────────────

function ErrorState({
  message,
  flow_id,
  children,
}: {
  message: string;
  flow_id: string;
  children?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <header style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Tag tone="danger">err</Tag>
        <Text variant="caption" muted>
          flow_id: {flow_id}
        </Text>
      </header>
      <EmptyState>{message}</EmptyState>
      {children}
    </div>
  );
}

function NotSupportedState({
  kind,
  flow_id,
}: {
  kind: string | undefined;
  flow_id: string;
}) {
  const t = useTranslations("shellV062.flowDrawer");
  return (
    <div
      data-testid="flow-drawer-not-supported"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <header style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Tag tone="amber">{t("notSupportedBadge")}</Tag>
        <Text variant="caption" muted>
          flow_id: {flow_id}
        </Text>
      </header>
      <EmptyState>{t("notSupportedHeadline")}</EmptyState>
      <Card variant="sunk">
        <Text variant="caption" muted>
          {t("notSupportedDetail", { kind: kind ?? "unknown" })}
        </Text>
      </Card>
    </div>
  );
}

// ── Loaded body ────────────────────────────────────────────────────────

function ReadyBody({
  payload,
  onResponded,
  onClose,
}: {
  payload: FlowRequestSingletonResponse;
  onResponded: () => void;
  onClose: () => void;
}) {
  const t = useTranslations("shellV062.flowDrawer");
  const fr = payload.flow_request;
  const participants = payload.participants;
  const respondability = payload.respondability;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Header fr={fr} />
      <ActorsRow fr={fr} participants={participants} />
      <FramingSection fr={fr} />
      <BackgroundSection fr={fr} />
      <OptionsSection fr={fr} />
      <EvidenceSection fr={fr} participants={participants} />

      <RespondSection
        flowId={fr.id}
        respondability={respondability}
        onResponded={onResponded}
        onClose={onClose}
      />

      <Text
        as="p"
        variant="caption"
        muted
        style={{ marginTop: 8, textAlign: "center" }}
      >
        {t("doctrine")}
      </Text>
    </div>
  );
}

function Header({ fr }: { fr: FlowRequestSingleton }) {
  const t = useTranslations("shellV062.flowDrawer");
  return (
    <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <Tag tone="accent">{fr.recipe_id}</Tag>
        <Tag
          tone={
            fr.status === "active"
              ? "accent"
              : fr.status === "completed"
                ? "ok"
                : fr.status === "blocked"
                  ? "amber"
                  : fr.status === "rejected"
                    ? "danger"
                    : "neutral"
          }
        >
          {fr.status}
        </Tag>
        {fr.stage && fr.stage !== fr.status ? (
          <Text variant="caption" muted>
            {fr.stage}
          </Text>
        ) : null}
        {fr.project_id ? (
          <Tag tone="neutral">{fr.project_id.slice(0, 8)}</Tag>
        ) : null}
      </div>
      <Text variant="body">{fr.title || fr.summary || fr.id}</Text>
      {fr.created_at ? (
        <Text variant="caption" muted>
          {t("createdAt", { at: formatIso(fr.created_at) })}
        </Text>
      ) : null}
    </header>
  );
}

function ActorsRow({
  fr,
  participants,
}: {
  fr: FlowRequestSingleton;
  participants: Record<string, FlowParticipant>;
}) {
  const t = useTranslations("shellV062.flowDrawer");
  return (
    <Card variant="sunk">
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Text variant="caption" muted>
          {t("from")}
        </Text>
        <Text variant="body">{nameFor(participants, fr.source_user_id)}</Text>
        <Text variant="caption" muted style={{ marginTop: 8 }}>
          {t("to")}
        </Text>
        <Text variant="body">
          {(fr.current_target_user_ids.length > 0
            ? fr.current_target_user_ids
            : fr.target_user_ids
          )
            .map((uid) => nameFor(participants, uid))
            .join(", ") || "—"}
        </Text>
      </div>
    </Card>
  );
}

function FramingSection({ fr }: { fr: FlowRequestSingleton }) {
  const t = useTranslations("shellV062.flowDrawer");
  if (!fr.framing_full) return null;
  return (
    <Card title={t("framingHeader")}>
      <pre
        style={{
          whiteSpace: "pre-wrap",
          margin: 0,
          fontFamily: "var(--wg-font-sans)",
          fontSize: "var(--wg-fs-body)",
          lineHeight: "var(--wg-lh-normal)",
          color: "var(--wg-ink)",
        }}
      >
        {fr.framing_full}
      </pre>
    </Card>
  );
}

function BackgroundSection({ fr }: { fr: FlowRequestSingleton }) {
  const t = useTranslations("shellV062.flowDrawer");
  if (!fr.background || fr.background.length === 0) return null;
  return (
    <Card title={t("backgroundHeader")}>
      <ul style={{ paddingLeft: 18, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {fr.background.map((b, i) => (
          <li key={i}>
            <Text variant="caption" muted>
              {b.source}
            </Text>
            <br />
            <Text variant="body">{b.snippet}</Text>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function OptionsSection({ fr }: { fr: FlowRequestSingleton }) {
  const t = useTranslations("shellV062.flowDrawer");
  if (!fr.options || fr.options.length === 0) return null;
  return (
    <Card title={t("optionsHeader")}>
      <ul style={{ paddingLeft: 18, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {fr.options.map((opt) => (
          <li key={opt.id}>
            <Text variant="body">{opt.label}</Text>
            {opt.reason ? (
              <>
                <br />
                <Text variant="caption" muted>
                  {opt.reason}
                </Text>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function EvidenceSection({
  fr,
  participants,
}: {
  fr: FlowRequestSingleton;
  participants: Record<string, FlowParticipant>;
}) {
  const t = useTranslations("shellV062.flowDrawer");
  const gates = fr.evidence?.human_gates ?? [];
  if (gates.length === 0) return null;
  return (
    <Card title={t("evidenceHeader")}>
      <ul style={{ paddingLeft: 18, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {gates.map((g, i) => (
          <li key={i}>
            <Text variant="body">
              {nameFor(participants, g.user_id)} · {g.action}
            </Text>
            {g.note ? (
              <>
                <br />
                <Text variant="caption" muted>
                  {g.note}
                </Text>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ── Respond ───────────────────────────────────────────────────────────

function RespondSection({
  flowId,
  respondability,
  onResponded,
  onClose,
}: {
  flowId: string;
  respondability: FlowRequestRespondability;
  onResponded: () => void;
  onClose: () => void;
}) {
  const t = useTranslations("shellV062.flowDrawer");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Honest non-respondable copy when the server says no.
  if (!respondability.respondable) {
    const reason = respondability.reason ?? "unknown";
    let body = t("respondDisabledGeneric");
    if (reason === "not_the_target") body = t("respondDisabledNotTarget");
    else if (reason.startsWith("route_status_"))
      body = t("respondDisabledStatus", { status: reason.replace("route_status_", "") });
    return (
      <Card variant="sunk" data-testid="flow-drawer-respond-disabled">
        <Text variant="caption" muted>
          {body}
        </Text>
      </Card>
    );
  }

  const onSubmit = async () => {
    if (busy) return;
    const trimmed = text.trim();
    if (!trimmed) {
      setError(t("errorEmpty"));
      return;
    }
    setBusy(true);
    setError(null);
    const result = await postFlowRequestResponse(flowId, trimmed);
    setBusy(false);
    if (!result.ok) {
      const code = result.error;
      if (code === "already_replied") setError(t("errorAlreadyReplied"));
      else if (code === "not_the_target") setError(t("errorNotTheTarget"));
      else if (code === "signal_not_found") setError(t("errorNotFound"));
      else if (code === "empty_response") setError(t("errorEmpty"));
      else if (code === "network") setError(t("errorNetwork"));
      else if (code === "not_respondable_yet")
        setError(t("errorNotRespondable"));
      else setError(t("errorGeneric"));
      return;
    }
    setText("");
    onResponded();
  };

  return (
    <Card title={t("respondHeader")} data-testid="flow-drawer-respond">
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("respondPlaceholder")}
          rows={4}
          disabled={busy}
          style={{
            width: "100%",
            padding: 10,
            fontFamily: "var(--wg-font-sans)",
            fontSize: "var(--wg-fs-body)",
            lineHeight: "var(--wg-lh-normal)",
            color: "var(--wg-ink)",
            background: "var(--wg-surface)",
            border: "1px solid var(--wg-line)",
            borderRadius: 8,
            resize: "vertical",
          }}
        />
        {error ? (
          <Text variant="caption" style={{ color: "var(--wg-danger)" }}>
            {error}
          </Text>
        ) : null}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            variant="primary"
            onClick={onSubmit}
            disabled={busy || text.trim().length === 0}
            data-testid="flow-drawer-respond-submit"
          >
            {busy ? t("sending") : t("send")}
          </Button>
        </div>
      </div>
    </Card>
  );
}
