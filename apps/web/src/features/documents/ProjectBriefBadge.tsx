// ProjectBriefBadge — distinguishing visual for the pinned project
// brief. Doctrine (DESIGN_LOCK §"Locked IA"): Project Brief is a
// pinned KB document, not a separate concept. The badge is what makes
// the brief stand apart from notes / attachments in the index.
//
// Visual: accent-blue Tag with a pin-style label. Sits on the
// DocumentCard header next to the title. Distinct from neutral scope
// chips so the brief reads as "the canonical doc for this scope" at
// a glance.
//
// Phase D scaffold (2026-05-13). v1 uses the existing Tag primitive
// in accent tone; if the brief needs more visual weight in Phase D.2
// (e.g. a pin icon), it gets added here, not at every call-site.

import { Tag } from "@/components/ui";

// TODO(i18n)
const LABEL = "Project Brief";

export function ProjectBriefBadge({ size = "sm" }: { size?: "sm" | "md" }) {
  return (
    <Tag tone="accent" size={size}>
      {LABEL}
    </Tag>
  );
}
