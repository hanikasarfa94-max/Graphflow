"use client";

// NewRoomModal — small modal for creating a room.
//
// POSTs to /api/projects/{id}/rooms with a name + selected members.
// Member picker is the project member list (the room must be a subset
// of the cell). Creator is always added by the backend, even if not
// explicitly checked here, so the picker offers other members only.
//
// On success the parent receives the new room id and decides what to
// do (typically: refresh the rooms list + navigate to the new room).

import { useEffect, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ApiError, createRoom } from "@/lib/api";

export interface ProjectMemberLite {
  user_id: string;
  username: string;
  display_name: string;
}

interface Props {
  projectId: string;
  // Project members the picker selects from. Caller pre-fetches via
  // ProjectState (so we don't double-fetch).
  members: ProjectMemberLite[];
  // Caller's own id — pre-checked + disabled in the picker (creator is
  // always added by the backend).
  currentUserId: string;
  open: boolean;
  onClose: () => void;
  // Optional callback fired AFTER navigation kicks off. Lets the parent
  // refresh its rooms list state if it caches one.
  onCreated?: (roomId: string) => void;
}

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.4)",
  zIndex: 60,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

const modalStyle: CSSProperties = {
  width: "min(440px, 92vw)",
  maxHeight: "min(80vh, 600px)",
  background: "#fff",
  borderRadius: "var(--wg-radius)",
  boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
};

const headerStyle: CSSProperties = {
  padding: "14px 16px",
  borderBottom: "1px solid var(--wg-line)",
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const bodyStyle: CSSProperties = {
  padding: 16,
  overflow: "auto",
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const footerStyle: CSSProperties = {
  padding: "12px 16px",
  borderTop: "1px solid var(--wg-line)",
  display: "flex",
  justifyContent: "flex-end",
  gap: 8,
};

const inputStyle: CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  fontSize: 14,
  border: "1px solid var(--wg-line)",
  borderRadius: 4,
  fontFamily: "inherit",
};

const memberRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 8px",
  borderRadius: 4,
  cursor: "pointer",
};

const primaryBtnStyle = (disabled: boolean): CSSProperties => ({
  padding: "6px 14px",
  fontSize: 13,
  border: "1px solid var(--wg-accent)",
  borderRadius: 3,
  background: disabled ? "var(--wg-line)" : "var(--wg-accent)",
  color: disabled ? "var(--wg-ink-soft)" : "#fff",
  cursor: disabled ? "not-allowed" : "pointer",
  fontWeight: 600,
});

const secondaryBtnStyle: CSSProperties = {
  padding: "6px 14px",
  fontSize: 13,
  border: "1px solid var(--wg-line)",
  borderRadius: 3,
  background: "#fff",
  color: "var(--wg-ink-soft)",
  cursor: "pointer",
};

export function NewRoomModal({
  projectId,
  members,
  currentUserId,
  open,
  onClose,
  onCreated,
}: Props) {
  const t = useTranslations("stream.rooms.newRoom");
  const router = useRouter();
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset on open so reopening doesn't carry stale state.
  useEffect(() => {
    if (open) {
      setName("");
      setSelected(new Set());
      setSubmitting(false);
      setError(null);
    }
  }, [open]);

  // Esc to close (browser default for many controls already handles
  // this on contained focus, but explicit handler covers all cases).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const otherMembers = members.filter((m) => m.user_id !== currentUserId);
  const trimmedName = name.trim();
  const canSubmit = trimmedName.length > 0 && !submitting;

  function toggle(uid: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }

  async function submit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const resp = await createRoom(projectId, {
        name: trimmedName,
        member_user_ids: Array.from(selected),
      });
      const roomId = resp.stream.id;
      onCreated?.(roomId);
      onClose();
      router.push(`/projects/${projectId}/rooms/${roomId}`);
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "message" in e.body
            ? String((e.body as { message?: unknown }).message ?? e.message)
            : `error ${e.status}`;
        setError(detail);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError(t("genericError"));
      }
      setSubmitting(false);
    }
  }

  return (
    <div
      style={overlayStyle}
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-room-title"
      onClick={onClose}
    >
      <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
        <div style={headerStyle}>
          <strong id="new-room-title" style={{ fontSize: 15 }}>
            {t("title")}
          </strong>
          <small
            style={{
              color: "var(--wg-ink-soft)",
              fontSize: 12,
              marginLeft: "auto",
            }}
          >
            {t("subtitle")}
          </small>
        </div>
        <div style={bodyStyle}>
          <div>
            <label
              htmlFor="new-room-name"
              style={{
                display: "block",
                fontSize: 12,
                color: "var(--wg-ink-soft)",
                marginBottom: 4,
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t("nameLabel")}
            </label>
            <input
              id="new-room-name"
              type="text"
              autoFocus
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("namePlaceholder")}
              style={inputStyle}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submit();
              }}
            />
          </div>
          <div>
            <div
              style={{
                fontSize: 12,
                color: "var(--wg-ink-soft)",
                marginBottom: 4,
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t("membersLabel", { count: selected.size + 1 })}
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {/* Always-on row for the creator (added server-side) */}
              <div
                style={{
                  ...memberRowStyle,
                  cursor: "default",
                  background: "var(--wg-accent-soft, #eef3ff)",
                }}
              >
                <input
                  type="checkbox"
                  checked
                  disabled
                  aria-label={t("youAlwaysIncluded")}
                />
                <strong style={{ fontSize: 13 }}>{t("youLabel")}</strong>
                <span
                  style={{
                    marginLeft: "auto",
                    fontSize: 11,
                    color: "var(--wg-ink-soft)",
                  }}
                >
                  {t("creatorBadge")}
                </span>
              </div>
              {otherMembers.length === 0 && (
                <p
                  style={{
                    margin: "8px 0 0",
                    fontSize: 12,
                    color: "var(--wg-ink-soft)",
                  }}
                >
                  {t("noOtherMembers")}
                </p>
              )}
              {otherMembers.map((m) => (
                <label key={m.user_id} style={memberRowStyle}>
                  <input
                    type="checkbox"
                    checked={selected.has(m.user_id)}
                    onChange={() => toggle(m.user_id)}
                  />
                  <span style={{ fontSize: 13 }}>
                    {m.display_name || m.username}
                  </span>
                  <span
                    style={{
                      marginLeft: "auto",
                      fontSize: 11,
                      color: "var(--wg-ink-soft)",
                      fontFamily: "var(--wg-font-mono)",
                    }}
                  >
                    @{m.username}
                  </span>
                </label>
              ))}
            </div>
          </div>
          {error && (
            <p
              style={{
                margin: 0,
                fontSize: 12,
                color: "var(--wg-warn, #b94a48)",
              }}
            >
              {error}
            </p>
          )}
        </div>
        <div style={footerStyle}>
          <button
            type="button"
            onClick={onClose}
            style={secondaryBtnStyle}
            disabled={submitting}
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            style={primaryBtnStyle(!canSubmit)}
            disabled={!canSubmit}
          >
            {submitting ? t("creating") : t("create")}
          </button>
        </div>
      </div>
    </div>
  );
}
