// /projects/[id]/meetings/[transcriptId] — Phase 2.B transcript detail.
//
// Server component. Shows the transcript (collapsible), the extracted
// signals grouped by kind, and a back link to the list. Accept actions
// live in SignalsPanel (client).

import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import {
  SignalsPanel,
  type ExtractedSignals,
} from "@/components/meetings/SignalsPanel";
import { TranscriptBody } from "@/components/meetings/TranscriptBody";
import { Card, Heading, Text } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";
import { formatIso } from "@/lib/time";

export const dynamic = "force-dynamic";

interface MeetingDetail {
  id: string;
  project_id: string;
  uploader_user_id: string | null;
  title: string;
  uploaded_at: string | null;
  metabolism_status: "pending" | "done" | "failed" | string;
  metabolism_started_at: string | null;
  metabolism_completed_at: string | null;
  participant_user_ids: string[];
  transcript_length: number;
  transcript_text: string;
  extracted_signals: ExtractedSignals;
  error_message: string | null;
}

interface DetailResponse {
  ok: boolean;
  transcript: MeetingDetail;
}

export default async function MeetingDetailPage({
  params,
}: {
  params: Promise<{ id: string; transcriptId: string }>;
}) {
  const { id, transcriptId } = await params;
  await requireUser(`/projects/${id}/meetings/${transcriptId}`);
  const t = await getTranslations("meeting");

  let detail: MeetingDetail | null = null;
  try {
    const res = await serverFetch<DetailResponse>(
      `/api/projects/${id}/meetings/${transcriptId}`,
    );
    detail = res.transcript;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }
  if (!detail) notFound();

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <nav>
        <Link
          href={`/projects/${id}/meetings`}
          style={{
            textDecoration: "none",
            color: "var(--wg-ink-soft)",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          ← {t("backToList")}
        </Link>
      </nav>

      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Heading level={2}>{detail.title || t("untitled")}</Heading>
        <Text variant="caption" muted>
          {detail.uploaded_at
            ? formatIso(detail.uploaded_at)
            : ""}{" "}
          · {detail.transcript_length} {t("chars")} · {detail.metabolism_status}
        </Text>
      </header>

      <Card title={t("transcriptHeading")}>
        <TranscriptBody text={detail.transcript_text} />
      </Card>

      <SignalsPanel
        projectId={id}
        transcriptId={transcriptId}
        signals={detail.extracted_signals || {}}
        status={detail.metabolism_status}
      />

      {detail.error_message ? (
        <Card accent="terracotta" title={t("errorHeading")}>
          <Text variant="caption">{detail.error_message}</Text>
        </Card>
      ) : null}
    </main>
  );
}
