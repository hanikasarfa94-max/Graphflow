// Memory-candidate action client — pure logic, no UI imports.
//
// Lives outside MemoryReviewDrawer.tsx so the bun:test suite can
// exercise the WG-envelope decoder without transitively pulling in
// lucide-react / DrawerHost / Next.js client-component machinery.
//
// Pairs with the live endpoints:
//   POST /api/memory-candidates/:id/accept
//   POST /api/memory-candidates/:id/defer
//   POST /api/memory-candidates/:id/reject
//   POST /api/memory-candidates/:id/reopen
//
// Returns a discriminated `ActionResult` — never throws. The caller
// matches on `result.error` to pick a bilingual i18n key.

import { ApiError, api } from "@/lib/api";

export type CandidateAction = "accept" | "defer" | "reject" | "reopen";

export interface ActionResult {
  ok: boolean;
  // Discriminated error kinds — match the BE error envelope so the
  // FE picks an i18n key without parsing prose.
  error?:
    | "authority_required"
    | "already_resolved"
    | "not_reopenable"
    | "not_found"
    | "not_a_member"
    | "network"
    | "unknown";
  required_role?: string;
}

// Reads from the WG error envelope (`{code, message, details,
// trace_id}` per packages/schemas/.../errors.py). The global FastAPI
// exception handler emits structured details — `message` is the
// short error name, `details` carries authority info.
export async function postCandidateAction(
  action: CandidateAction,
  id: string,
): Promise<ActionResult> {
  try {
    await api(`/api/memory-candidates/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      body: {},
    });
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError) {
      const body = (err.body ?? {}) as Record<string, unknown>;
      const message =
        typeof body["message"] === "string" ? body["message"] : null;
      const details = (body["details"] ?? {}) as Record<string, unknown>;

      if (err.status === 403 && message === "authority_required") {
        const required = details["required_roles"];
        const role =
          Array.isArray(required) && required.length > 0
            ? String(required[0])
            : "reviewer";
        return { ok: false, error: "authority_required", required_role: role };
      }
      if (message === "already_resolved")
        return { ok: false, error: "already_resolved" };
      if (message === "not_reopenable")
        return { ok: false, error: "not_reopenable" };
      if (message === "not_found" || err.status === 404)
        return { ok: false, error: "not_found" };
      if (message === "not_a_member" || err.status === 403)
        return { ok: false, error: "not_a_member" };
      return { ok: false, error: "unknown" };
    }
    return { ok: false, error: "network" };
  }
}
