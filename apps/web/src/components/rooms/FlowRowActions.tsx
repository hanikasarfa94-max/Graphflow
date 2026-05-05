"use client";

// FlowRowActions — C.1.c source-side mutation surface.
//
// Density choice (per user UX guidance): visible row shows
// `Open` link + `Accept` button + `More` toggle. The remaining three
// actions (Counter back / Send follow-up / Escalate to gate) live
// behind `More`. counter_back and custom_followup expand an inline
// form for `framing` before posting.
//
// Contract: this component reads ONLY `packet.next_actions`. It does
// NOT infer eligibility from `recipe_id`, `routed_signal_id`, or
// `current_target_user_ids`. The BE projection is the sole source of
// truth for what the viewer can do right now (memo §11). When B's
// projection later widens to KB/handoff actions, this component will
// surface them with no FE change.

import Link from "next/link";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  extractApiErrorDetail,
} from "@/lib/api";
import {
  actionRequiresFraming,
  isMutationAction,
  postFlowAction,
  type FlowAction,
  type FlowActionBody,
  type FlowActionKind,
  type FlowPacket,
} from "@/lib/flows";

interface Props {
  packet: FlowPacket;
  // Parent calls this on success so the three buckets re-fetch.
  onActed?: () => void;
}

// Map BE error code (carried in the global handler's `message` field
// as "<code>: <detail>") to the FE i18n key. Fallback is `generic`.
const ERROR_CODE_TO_KEY: Record<string, string> = {
  flow_not_found: "flowNotFound",
  unsupported_flow_recipe: "unsupportedFlowRecipe",
  unsupported_action: "unsupportedAction",
  not_source_user: "notSourceUser",
  not_ready_for_source_action: "notReadyForSourceAction",
  validation_error: "validationError",
  domain_error: "domainError",
};

function extractErrorKey(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = extractApiErrorDetail(err.body) ?? "";
    // BE format: "<code>: <subdetail>" or just "<code>"
    const colonIdx = detail.indexOf(":");
    const code = (colonIdx >= 0 ? detail.slice(0, colonIdx) : detail).trim();
    if (code && ERROR_CODE_TO_KEY[code]) return ERROR_CODE_TO_KEY[code];
  }
  return "generic";
}

export function FlowRowActions({ packet, onActed }: Props) {
  const t = useTranslations("flows");

  // Open link — preserves existing Slice B / B.2 behaviour. Read from
  // next_actions[kind=open] so the BE owns the href.
  const openAction = packet.next_actions.find((a) => a.kind === "open");

  // Mutation actions — narrowed to the four C.1 source-side kinds.
  const mutationActions = packet.next_actions.filter((a) =>
    isMutationAction(a.kind),
  );
  const accept = mutationActions.find((a) => a.kind === "accept");
  const otherMutations = mutationActions.filter(
    (a) => a.kind !== "accept",
  );

  return (
    <div
      data-testid="flow-row-actions"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        flexWrap: "wrap",
        justifyContent: "flex-end",
      }}
    >
      {openAction?.href ? (
        <Link
          href={openAction.href}
          data-testid="flow-row-open"
          style={openLinkStyle}
        >
          {t("open")}
        </Link>
      ) : (
        <span style={{ ...openLinkStyle, opacity: 0.5, cursor: "default" }}>
          {t("openMissing")}
        </span>
      )}
      {accept ? (
        <ActionWithMore
          packet={packet}
          accept={accept}
          others={otherMutations}
          onActed={onActed}
        />
      ) : null}
    </div>
  );
}

function ActionWithMore({
  packet,
  accept,
  others,
  onActed,
}: {
  packet: FlowPacket;
  accept: FlowAction;
  others: FlowAction[];
  onActed?: () => void;
}) {
  const t = useTranslations("flows");
  const [moreOpen, setMoreOpen] = useState(false);
  const [pendingForm, setPendingForm] = useState<FlowActionKind | null>(null);
  const [posting, setPosting] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Outside-click + Escape close the more-menu. We don't auto-close
  // the inline form here — that has its own Cancel button so users
  // don't accidentally lose typed framing.
  useEffect(() => {
    if (!moreOpen) return;
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (e.target instanceof Node && wrapRef.current.contains(e.target)) {
        return;
      }
      setMoreOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMoreOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [moreOpen]);

  async function fireAction(body: FlowActionBody): Promise<void> {
    setPosting(true);
    setErrorKey(null);
    try {
      await postFlowAction(packet.project_id, packet.id, body);
      // Clear local form / menu state and let the parent re-fetch.
      setPendingForm(null);
      setMoreOpen(false);
      onActed?.();
    } catch (err) {
      setErrorKey(extractErrorKey(err));
    } finally {
      setPosting(false);
    }
  }

  function clickAccept() {
    void fireAction({ action: "accept" });
  }

  function clickOther(kind: FlowActionKind) {
    setMoreOpen(false);
    if (actionRequiresFraming(kind)) {
      setPendingForm(kind);
      return;
    }
    // No framing required (escalate_to_gate) — fire immediately.
    if (kind === "escalate_to_gate") {
      void fireAction({ action: "escalate_to_gate" });
    }
  }

  return (
    <div
      ref={wrapRef}
      style={{ position: "relative", display: "flex", alignItems: "center", gap: 6 }}
    >
      <button
        type="button"
        data-testid="flow-action-accept"
        onClick={clickAccept}
        disabled={posting}
        style={primaryBtnStyle(posting)}
      >
        {t("actions.accept")}
      </button>
      {others.length > 0 ? (
        <button
          type="button"
          data-testid="flow-action-more"
          aria-expanded={moreOpen}
          aria-label={moreOpen ? t("actions.moreClose") : t("actions.moreOpen")}
          onClick={() => setMoreOpen((v) => !v)}
          disabled={posting}
          style={moreBtnStyle(moreOpen)}
        >
          {t("actions.more")} ▾
        </button>
      ) : null}
      {moreOpen ? (
        <div
          role="menu"
          data-testid="flow-action-more-menu"
          style={moreMenuStyle}
        >
          {others.map((a) => (
            <button
              key={a.id}
              type="button"
              role="menuitem"
              data-testid={`flow-action-${a.kind}`}
              onClick={() => clickOther(a.kind as FlowActionKind)}
              disabled={posting}
              style={menuItemStyle}
            >
              {t(`actions.${camelAction(a.kind as FlowActionKind)}`)}
            </button>
          ))}
        </div>
      ) : null}
      {pendingForm ? (
        <FramingForm
          kind={pendingForm}
          posting={posting}
          onCancel={() => setPendingForm(null)}
          onSubmit={(framing, note) => {
            const body: FlowActionBody =
              pendingForm === "counter_back"
                ? { action: "counter_back", framing, note: note || undefined }
                : {
                    action: "custom_followup",
                    framing,
                    note: note || undefined,
                  };
            void fireAction(body);
          }}
        />
      ) : null}
      {errorKey ? (
        <span
          data-testid="flow-action-error"
          role="alert"
          style={errorStyle}
        >
          {t(`errors.${errorKey}`)}
        </span>
      ) : null}
    </div>
  );
}

function FramingForm({
  kind,
  posting,
  onCancel,
  onSubmit,
}: {
  kind: FlowActionKind;
  posting: boolean;
  onCancel: () => void;
  onSubmit: (framing: string, note: string) => void;
}) {
  const t = useTranslations("flows");
  const [framing, setFraming] = useState("");
  const [note, setNote] = useState("");
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  // Auto-focus the textarea so the user can start typing immediately.
  useEffect(() => {
    taRef.current?.focus();
  }, []);

  const promptKey =
    kind === "counter_back"
      ? "form.counterBackPrompt"
      : "form.customFollowupPrompt";

  return (
    <div data-testid="flow-action-form" style={formStyle}>
      <div style={formPromptStyle}>{t(promptKey)}</div>
      <textarea
        ref={taRef}
        data-testid="flow-action-form-framing"
        value={framing}
        onChange={(e) => setFraming(e.target.value)}
        placeholder={t("form.framingPlaceholder")}
        rows={3}
        maxLength={4000}
        style={textareaStyle}
      />
      <input
        type="text"
        data-testid="flow-action-form-note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={t("form.notePlaceholder")}
        maxLength={1000}
        style={inputStyle}
      />
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button
          type="button"
          data-testid="flow-action-form-cancel"
          onClick={onCancel}
          disabled={posting}
          style={secondaryBtnStyle(posting)}
        >
          {t("form.cancel")}
        </button>
        <button
          type="button"
          data-testid="flow-action-form-send"
          onClick={() => onSubmit(framing.trim(), note.trim())}
          disabled={posting || !framing.trim()}
          style={primaryBtnStyle(posting || !framing.trim())}
        >
          {posting ? t("form.sending") : t("form.send")}
        </button>
      </div>
    </div>
  );
}

function camelAction(
  kind: FlowActionKind,
): "accept" | "counterBack" | "escalateToGate" | "customFollowup" {
  switch (kind) {
    case "accept":
      return "accept";
    case "counter_back":
      return "counterBack";
    case "escalate_to_gate":
      return "escalateToGate";
    case "custom_followup":
      return "customFollowup";
  }
}

// ---- styles --------------------------------------------------------------

const openLinkStyle: CSSProperties = {
  alignSelf: "center",
  padding: "4px 10px",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  border: "1px solid var(--wg-line)",
  borderRadius: 3,
  background: "#fff",
  color: "var(--wg-accent)",
  textDecoration: "none",
  whiteSpace: "nowrap",
};

function primaryBtnStyle(disabled: boolean): CSSProperties {
  return {
    padding: "4px 10px",
    fontSize: 11,
    fontFamily: "var(--wg-font-mono)",
    border: "1px solid var(--wg-accent)",
    borderRadius: 3,
    background: disabled ? "var(--wg-accent-soft, rgba(21,91,213,0.06))" : "var(--wg-accent)",
    color: disabled ? "var(--wg-ink-soft)" : "#fff",
    cursor: disabled ? "not-allowed" : "pointer",
    whiteSpace: "nowrap",
  };
}

function secondaryBtnStyle(disabled: boolean): CSSProperties {
  return {
    padding: "4px 10px",
    fontSize: 11,
    fontFamily: "var(--wg-font-mono)",
    border: "1px solid var(--wg-line)",
    borderRadius: 3,
    background: "#fff",
    color: "var(--wg-ink-soft)",
    cursor: disabled ? "not-allowed" : "pointer",
  };
}

function moreBtnStyle(open: boolean): CSSProperties {
  return {
    padding: "4px 8px",
    fontSize: 11,
    fontFamily: "var(--wg-font-mono)",
    border: "1px solid var(--wg-line)",
    borderRadius: 3,
    background: open ? "var(--wg-accent-soft, rgba(21,91,213,0.06))" : "#fff",
    color: "var(--wg-ink-soft)",
    cursor: "pointer",
  };
}

const moreMenuStyle: CSSProperties = {
  position: "absolute",
  top: "calc(100% + 4px)",
  right: 0,
  minWidth: 160,
  padding: 4,
  background: "#fff",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  boxShadow: "0 6px 18px rgba(0,0,0,0.08)",
  zIndex: 30,
  display: "flex",
  flexDirection: "column",
};

const menuItemStyle: CSSProperties = {
  padding: "6px 10px",
  fontSize: 12,
  fontFamily: "var(--wg-font-sans)",
  border: "none",
  background: "transparent",
  color: "var(--wg-ink)",
  textAlign: "left",
  cursor: "pointer",
  borderRadius: 3,
};

const formStyle: CSSProperties = {
  // Form pops below the action row. Absolute positioning keeps the
  // packet row's height stable; relative parent is FlowRowActions's
  // wrapper which also hosts the more-menu.
  position: "absolute",
  top: "calc(100% + 6px)",
  right: 0,
  width: 320,
  padding: 10,
  background: "#fff",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  boxShadow: "0 6px 18px rgba(0,0,0,0.08)",
  zIndex: 30,
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const formPromptStyle: CSSProperties = {
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: "var(--wg-ink-soft)",
};

const textareaStyle: CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  fontSize: 12,
  fontFamily: "var(--wg-font-sans)",
  border: "1px solid var(--wg-line)",
  borderRadius: 3,
  resize: "vertical",
  minHeight: 60,
};

const inputStyle: CSSProperties = {
  width: "100%",
  padding: "5px 8px",
  fontSize: 11,
  fontFamily: "var(--wg-font-sans)",
  border: "1px solid var(--wg-line)",
  borderRadius: 3,
};

const errorStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--wg-accent)",
  marginLeft: 8,
};
