// Flow-request action client — pure logic, no UI imports.
//
// RW-9 (2026-05-13). Lives outside FlowDrawer.tsx so the bun:test
// suite can exercise the wire-decoder without transitively pulling in
// lucide-react / DrawerHost / Next.js client-component machinery.
//
// Pairs with:
//   GET  /api/flow-requests/:id            singleton read
//   POST /api/flow-requests/:id/respond    direct text response
//
// Returns discriminated results — never throws. Callers match on
// `result.error` to pick a bilingual i18n key.

import { ApiError, api } from "@/lib/api";

import type {
  FlowRequestRespondResponse,
  FlowRequestSingletonResponse,
} from "./types";

// ── GET /api/flow-requests/:id ───────────────────────────────────────

export type FetchFlowRequestResult =
  | { ok: true; data: FlowRequestSingletonResponse }
  | {
      ok: false;
      error:
        | "not_supported_yet"
        | "not_found"
        | "forbidden"
        | "network"
        | "unknown";
      unsupportedKind?: string;
    };

// The 422 not_supported_yet detail is `not_supported_yet:<kind>`
// (e.g. `not_supported_yet:kb`). Parse the suffix so the FE can show
// the kind in the honest-empty state without parsing prose.
function parseUnsupportedKind(message: string | null): string | undefined {
  if (!message) return undefined;
  const colon = message.indexOf(":");
  if (colon === -1) return undefined;
  const kind = message.slice(colon + 1).trim();
  return kind || undefined;
}

export async function fetchFlowRequest(
  flowId: string,
): Promise<FetchFlowRequestResult> {
  try {
    const data = await api<FlowRequestSingletonResponse>(
      `/api/flow-requests/${encodeURIComponent(flowId)}`,
    );
    return { ok: true, data };
  } catch (err) {
    if (err instanceof ApiError) {
      const body = (err.body ?? {}) as Record<string, unknown>;
      const message =
        typeof body["message"] === "string"
          ? body["message"]
          : typeof body["detail"] === "string"
            ? body["detail"]
            : null;

      if (err.status === 422 && message?.startsWith("not_supported_yet")) {
        return {
          ok: false,
          error: "not_supported_yet",
          unsupportedKind: parseUnsupportedKind(message),
        };
      }
      if (err.status === 404) return { ok: false, error: "not_found" };
      if (err.status === 403) return { ok: false, error: "forbidden" };
      return { ok: false, error: "unknown" };
    }
    return { ok: false, error: "network" };
  }
}

// ── POST /api/flow-requests/:id/respond ──────────────────────────────

export type RespondResult =
  | { ok: true; data: FlowRequestRespondResponse }
  | {
      ok: false;
      error:
        | "not_respondable_yet"
        | "not_the_target"
        | "already_replied"
        | "empty_response"
        | "signal_not_found"
        | "lint_paused"
        | "network"
        | "unknown";
    };

export async function postFlowRequestResponse(
  flowId: string,
  text: string,
): Promise<RespondResult> {
  try {
    const data = await api<FlowRequestRespondResponse>(
      `/api/flow-requests/${encodeURIComponent(flowId)}/respond`,
      {
        method: "POST",
        body: { kind: "direct_response", text },
      },
    );
    return { ok: true, data };
  } catch (err) {
    if (err instanceof ApiError) {
      const body = (err.body ?? {}) as Record<string, unknown>;
      const message =
        typeof body["message"] === "string"
          ? body["message"]
          : typeof body["detail"] === "string"
            ? body["detail"]
            : null;

      // Pass through the routing service's error vocabulary verbatim.
      // The endpoint forwards `signal_not_found` / `not_the_target` /
      // `already_replied` / `empty_reply` straight from RoutingService.
      if (message?.startsWith("not_respondable_yet"))
        return { ok: false, error: "not_respondable_yet" };
      if (message === "not_the_target" || err.status === 403)
        return { ok: false, error: "not_the_target" };
      if (message === "already_replied" || err.status === 409)
        return { ok: false, error: "already_replied" };
      if (message === "signal_not_found" || err.status === 404)
        return { ok: false, error: "signal_not_found" };
      if (message === "lint_paused")
        return { ok: false, error: "lint_paused" };
      if (
        message === "empty_reply" ||
        message === "empty_response" ||
        err.status === 422
      )
        return { ok: false, error: "empty_response" };
      return { ok: false, error: "unknown" };
    }
    return { ok: false, error: "network" };
  }
}
