"use client";

// RoomShell — page-level layout for /projects/[id]/rooms/[roomId].
//
// Sits inside the existing project layout (ProjectLayout + ProjectNav
// supply column 1 + 2). The shell renders header + 2-column body
// (timeline + workbench), matching the "thin 4-column scaffold" codex
// recommended over a full N.2 layout port.
//
// Responsive: workbench auto-collapses below 1024px to a top-bar
// badge that reopens it as a side sheet.

import { useEffect, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { useRoomTimeline } from "@/hooks/useRoomTimeline";
import type { RoomSummary, StreamMemberSummary } from "@/lib/api";

import { RoomStreamTimeline } from "./RoomStreamTimeline";
import { RoomWorkbench } from "./RoomWorkbench";

interface Props {
  projectId: string;
  currentUserId: string;
  room: RoomSummary;
  // All rooms in this project, keyed by id, used by DecisionCard's
  // vote-scope explainer to render names + member counts.
  roomNameById: Record<string, { name: string; memberCount: number }>;
}

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "10px 16px",
  borderBottom: "1px solid var(--wg-line)",
  background: "#fff",
};

const memberAvatarStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 24,
  height: 24,
  borderRadius: "50%",
  background: "var(--wg-accent-soft, #eef3ff)",
  color: "var(--wg-accent, #2451b5)",
  fontSize: 11,
  fontWeight: 600,
  marginLeft: -6,
  border: "2px solid #fff",
};

function MemberAvatars({ members }: { members: StreamMemberSummary[] }) {
  const visible = members.slice(0, 5);
  const overflow = members.length - visible.length;
  return (
    <div
      style={{ display: "inline-flex", alignItems: "center", marginLeft: 8 }}
    >
      {visible.map((m) => (
        <span
          key={m.user_id}
          style={memberAvatarStyle}
          title={m.display_name || m.username}
        >
          {(m.display_name || m.username || "?").charAt(0).toUpperCase()}
        </span>
      ))}
      {overflow > 0 && (
        <span style={{ ...memberAvatarStyle, background: "#eee" }}>
          +{overflow}
        </span>
      )}
    </div>
  );
}

export function RoomShell({
  projectId,
  currentUserId,
  room,
  roomNameById,
}: Props) {
  const t = useTranslations("stream.rooms");
  const timeline = useRoomTimeline({ projectId, roomId: room.id });
  const [workbenchOpen, setWorkbenchOpen] = useState(true);
  const [isWide, setIsWide] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(min-width: 1024px)");
    const apply = () => setIsWide(mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const memberCount = room.members?.length ?? 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "calc(100vh - var(--wg-shell-top, 0px))",
        minHeight: 0,
      }}
    >
      <header style={headerStyle}>
        <strong style={{ fontSize: 15 }}>
          {room.name ?? t("untitledRoom")}
        </strong>
        <span
          style={{
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {t("memberCount", { count: memberCount })}
        </span>
        <MemberAvatars members={room.members ?? []} />
        <div style={{ flex: 1 }} />
        {!workbenchOpen && (
          <button
            type="button"
            onClick={() => setWorkbenchOpen(true)}
            style={{
              padding: "4px 10px",
              fontSize: 12,
              border: "1px solid var(--wg-line)",
              borderRadius: 3,
              background: "#fff",
              cursor: "pointer",
              color: "var(--wg-ink-soft)",
            }}
            aria-expanded="false"
          >
            {t("workbenchOpen")}
            {timeline.pendingSuggestions.length > 0 && (
              <span
                style={{
                  marginLeft: 6,
                  display: "inline-block",
                  minWidth: 16,
                  padding: "0 5px",
                  fontSize: 10,
                  fontWeight: 600,
                  borderRadius: 8,
                  background: "var(--wg-warn, #d99500)",
                  color: "#fff",
                  textAlign: "center",
                }}
              >
                {timeline.pendingSuggestions.length}
              </span>
            )}
          </button>
        )}
      </header>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns:
            workbenchOpen && isWide ? "1fr 360px" : "1fr",
        }}
      >
        <RoomStreamTimeline
          projectId={projectId}
          streamId={room.id}
          currentUserId={currentUserId}
          roomNameById={roomNameById}
          timeline={timeline}
        />
        {workbenchOpen && isWide && (
          <RoomWorkbench
            projectId={projectId}
            timeline={timeline}
            open={workbenchOpen}
            onClose={() => setWorkbenchOpen(false)}
          />
        )}
      </div>
      {/* Mobile workbench sheet: when narrow + open, render as overlay. */}
      {workbenchOpen && !isWide && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            zIndex: 50,
          }}
          onClick={() => setWorkbenchOpen(false)}
        >
          <div
            style={{
              position: "absolute",
              right: 0,
              top: 0,
              bottom: 0,
              width: "min(420px, 92vw)",
              background: "#fff",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <RoomWorkbench
              projectId={projectId}
              timeline={timeline}
              open
              onClose={() => setWorkbenchOpen(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
