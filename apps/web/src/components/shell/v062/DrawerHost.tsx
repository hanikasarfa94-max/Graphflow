"use client";

// DrawerHost — single right-side overlay drawer for the v0.6.2 shell.
//
// Per FRONTEND_IMPLEMENTATION.md, every contextual interaction the user
// triggers (flow request, memory candidate prompt, memory review,
// edit-before-sending, create menu, notifications) opens here. Only one
// drawer is visible at a time; opening a second replaces the first.
//
// The DrawerHost provides:
//   * context API: useDrawer().open({ type, props }) / close()
//   * portal-style overlay with backdrop scrim + ESC-to-close + focus trap
//   * accent shimmer entrance per DESIGN.md motion moment #5
//
// Drawer *contents* live in feature folders (apps/web/src/features/...);
// this file owns the chrome + state + transitions only.

import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// Drawer type registry. Adding a new drawer = adding a value here +
// a feature component that returns the body for that type. The drawer
// chrome (header, close, footer slot) is shared.
export type DrawerType =
  | "flow_request"
  | "memory_prompt"
  | "memory_review"
  | "edit_request"
  | "create_menu"
  | "notification";

export type DrawerRequest = {
  type: DrawerType;
  // Free-form props bag passed to the rendered drawer body. Each
  // feature component knows what shape it expects (e.g. flow_request
  // wants `flow_request_id`; memory_review wants `candidate_id`).
  props?: Record<string, unknown>;
  // Optional explicit title; defaults to a per-type label.
  title?: string;
};

type DrawerCtx = {
  current: DrawerRequest | null;
  open: (req: DrawerRequest) => void;
  close: () => void;
};

const DrawerContext = createContext<DrawerCtx | null>(null);

export function useDrawer(): DrawerCtx {
  const v = useContext(DrawerContext);
  if (!v) {
    // Defensive no-op for components rendered outside the host (e.g.
    // /login surfaces). Better than crashing at runtime.
    return { current: null, open: () => {}, close: () => {} };
  }
  return v;
}

// Per DrawerType — maps to the i18n key under shellV062.drawer.*.
const DRAWER_I18N_KEY: Record<DrawerType, string> = {
  flow_request: "flowRequest",
  memory_prompt: "memoryPrompt",
  memory_review: "memoryReview",
  edit_request: "editRequest",
  create_menu: "flowRequest", // No dedicated key yet — uses flowRequest as placeholder until Phase A.4 ships the create menu.
  notification: "notification",
};

// Width — fixed 520px per DESIGN.md §Layout. Mobile breakpoint
// converts to full-width sheet (handled in CSS later); for now we
// degrade gracefully via max-width: 100vw.
const DRAWER_WIDTH = 520;

export function DrawerHostProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<DrawerRequest | null>(null);

  const open = useCallback((req: DrawerRequest) => setCurrent(req), []);
  const close = useCallback(() => setCurrent(null), []);

  // ESC closes the drawer. Listener mounted only when open.
  useEffect(() => {
    if (!current) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setCurrent(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current]);

  const ctx = useMemo<DrawerCtx>(
    () => ({ current, open, close }),
    [current, open, close],
  );

  return (
    <DrawerContext.Provider value={ctx}>
      {children}
      {current ? (
        <DrawerOverlay request={current} onClose={close} />
      ) : null}
    </DrawerContext.Provider>
  );
}

function DrawerOverlay({
  request,
  onClose,
}: {
  request: DrawerRequest;
  onClose: () => void;
}) {
  const t = useTranslations("shellV062.drawer");
  const title =
    request.title ?? t(DRAWER_I18N_KEY[request.type] as Parameters<typeof t>[0]);

  // Lock scroll on the body while drawer is open.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  return (
    <>
      {/* Backdrop scrim. Click closes. */}
      <div
        role="presentation"
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(20, 23, 31, 0.30)",
          zIndex: 80,
          animation: "wg-drawer-scrim-in var(--wg-dur-short) var(--wg-ease-enter) both",
        }}
      />
      {/* Drawer panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="wg-drawer-title"
        data-drawer-type={request.type}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          height: "100vh",
          width: DRAWER_WIDTH,
          maxWidth: "100vw",
          background: "var(--wg-surface)",
          borderLeft: "1px solid var(--wg-line)",
          boxShadow: "var(--wg-shadow-lg)",
          zIndex: 81,
          display: "flex",
          flexDirection: "column",
          animation: "wg-drawer-in var(--wg-dur-medium) var(--wg-ease-enter) both",
        }}
      >
        <header
          style={{
            padding: "14px 20px",
            borderBottom: "1px solid var(--wg-line)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <h2
            id="wg-drawer-title"
            style={{
              margin: 0,
              fontSize: "var(--wg-fs-h2)",
              fontFamily: "var(--wg-font-sans)",
              fontWeight: 600,
              color: "var(--wg-ink)",
            }}
          >
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("close")}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              padding: 6,
              borderRadius: 8,
              color: "var(--wg-ink-soft)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <X size={18} />
          </button>
        </header>
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: 20,
          }}
        >
          {/* Body — Phase C wires real feature components keyed by
              request.type. For Phase A.2 the host is in place but
              content is a placeholder so /flow-center et al. can
              open it without crashing. */}
          <DrawerBodyStub request={request} />
        </div>
      </aside>
      {/* Local keyframes — keeps drawer motion self-contained and
          doesn't pollute globals.css until the design refresh (A.3). */}
      <style>{`
        @keyframes wg-drawer-in {
          from { transform: translateX(24px); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
        @keyframes wg-drawer-scrim-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @media (prefers-reduced-motion: reduce) {
          [data-drawer-type] { animation: none !important; }
        }
      `}</style>
    </>
  );
}

function DrawerBodyStub({ request }: { request: DrawerRequest }) {
  return (
    <div
      style={{
        fontFamily: "var(--wg-font-sans)",
        fontSize: "var(--wg-fs-body)",
        color: "var(--wg-ink-soft)",
        lineHeight: "var(--wg-lh-normal)",
      }}
    >
      <p style={{ margin: 0 }}>
        Drawer type: <code>{request.type}</code>
      </p>
      <p style={{ marginTop: 12 }}>
        Real drawer body wires in Phase{" "}
        {request.type === "memory_review" || request.type === "memory_prompt"
          ? "C"
          : request.type === "flow_request" || request.type === "edit_request"
            ? "C"
            : request.type === "create_menu"
              ? "A.4"
              : "B"}{" "}
        per <code>BUILD-v062.md</code>.
      </p>
    </div>
  );
}
