// Conversation-side action client — pure logic, no UI imports.
//
// Phase RW-5 (2026-05-13): lives outside ConversationComposer.tsx so
// the bun:test suite can exercise the wire-shape decoder without
// pulling in the next-intl / @/components/ui / DrawerHost tree.
//
// Pairs with the live endpoint:
//   POST /api/conversations/:id/messages   { body: string }
//
// Returns a discriminated `SendResult` — never throws. The caller
// matches on `result.error` to pick a bilingual i18n key.

import { ApiError, api } from "@/lib/api";

export interface SendResult {
  ok: boolean;
  error?:
    | "not_a_member"
    | "stream_not_found"
    | "validation"
    | "network"
    | "unknown";
}

// Reads from the WG error envelope (`{code, message, details,
// trace_id}` per packages/schemas/.../errors.py). The global FastAPI
// exception handler emits `message` as the short error name for
// string `detail` raises (which this endpoint uses).
export async function postConversationMessage(
  conversation_id: string,
  body: string,
): Promise<SendResult> {
  // Defensive client-side trim — the BE pydantic schema requires
  // min_length=1, but trimming here surfaces the validation error
  // before the network round-trip when the user sent only whitespace.
  const trimmed = body.trim();
  if (trimmed.length === 0) {
    return { ok: false, error: "validation" };
  }

  try {
    await api(
      `/api/conversations/${encodeURIComponent(conversation_id)}/messages`,
      {
        method: "POST",
        body: { body: trimmed },
      },
    );
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError) {
      const respBody = (err.body ?? {}) as Record<string, unknown>;
      const message =
        typeof respBody["message"] === "string" ? respBody["message"] : null;

      if (message === "stream_not_found" || err.status === 404) {
        return { ok: false, error: "stream_not_found" };
      }
      if (message === "not_a_member" || err.status === 403) {
        return { ok: false, error: "not_a_member" };
      }
      if (err.status === 422 || err.status === 400) {
        return { ok: false, error: "validation" };
      }
      return { ok: false, error: "unknown" };
    }
    return { ok: false, error: "network" };
  }
}
