// RecognitionPolicyBadge — tone-keyed visual for TaskRecognitionPolicy.
//
// Phase D scaffold (2026-05-13). One of the five doctrine-load-bearing
// pills of the v0.6.2 IA: every task that exists past the candidate
// stage has a recognition policy, and the policy is non-optional on
// /api/tasks/:id/promote.
//
// Tone mapping (per task brief):
//   none                   → muted slate   (uncommon "no team gate" path)
//   assignee_accept        → ok green
//   project_owner_confirm  → accent blue
//   flow_required          → ai violet
//   review_required        → amber
//
// The Tag primitive in @/components/ui covers neutral/accent/amber/ok/
// danger — there is no "ai" tone built-in. To honor "Existing UI
// primitives only," `flow_required` is rendered as a Tag with an
// inline color override that points at the existing `--wg-ai*` CSS
// vars defined in apps/web/src/app/globals.css (lines 42-45). No new
// primitive is introduced.

// TODO(i18n): externalize POLICY_LABEL strings.

import { Tag } from "@/components/ui";

import type { TaskRecognitionPolicy } from "./types";

const POLICY_LABEL: Record<TaskRecognitionPolicy, string> = {
  none: "No team gate",
  assignee_accept: "Assignee accepts",
  project_owner_confirm: "Owner confirms",
  flow_required: "Flow required",
  review_required: "Review required",
};

// Tone-keyed mapping. The four tones below resolve to existing Tag
// tones; `flow_required` overrides Tag's tint via inline CSS vars so
// the "ai violet" surface shows through without inventing a sixth
// Tag tone.
const POLICY_TONE: Record<
  TaskRecognitionPolicy,
  "neutral" | "accent" | "amber" | "ok"
> = {
  none: "neutral",
  assignee_accept: "ok",
  project_owner_confirm: "accent",
  flow_required: "neutral", // overridden via style below to --wg-ai
  review_required: "amber",
};

export function RecognitionPolicyBadge({
  policy,
  size = "sm",
}: {
  policy: TaskRecognitionPolicy;
  size?: "sm" | "md";
}) {
  const label = POLICY_LABEL[policy];
  const tone = POLICY_TONE[policy];

  if (policy === "flow_required") {
    // Violet override — uses --wg-ai* tokens directly so the badge
    // signals "AI-mediated handoff" per DESIGN.md §Color.
    return (
      <Tag
        tone={tone}
        size={size}
        style={{
          background: "var(--wg-ai-soft)",
          color: "var(--wg-ai)",
          border: "1px solid transparent",
        }}
      >
        {label}
      </Tag>
    );
  }

  return (
    <Tag tone={tone} size={size}>
      {label}
    </Tag>
  );
}
