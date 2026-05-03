"use client";

// Sprint 1b — time-cursor scrubber strip.
//
// Sits above the React Flow canvas. The slider's left edge is the
// project's created_at; the right edge is "now" (server clock, pulled
// from /timeline so client clock skew doesn't misrender). The user
// drags the handle to any past timestamp and the parent GraphCanvas
// fetches /graph-at and swaps the state in place.
//
// Design notes:
//   * The strip is dense — just a slider + event markers + a "Live"
//     button. No video-player chrome; WorkGraph is a work tool, not a
//     timeline editor, and the graph itself is the content.
//   * Event markers are dots positioned at the normalized x of their
//     timestamp. Colors distinguish decisions (accent) from conflicts
//     (severity-tinted) from status transitions (ink-soft). Hovering
//     a marker previews the entity; clicking snaps the cursor to it.
//   * Reduced-motion: the slider doesn't animate position changes; the
//     parent canvas' dim-to-past transition respects the same media
//     query in CSS.
//
// Why a dedicated component:
//   GraphCanvas.tsx is already ~1700 LOC. Splitting the strip out keeps
//   the scrubber self-contained — strip-level state (slider value,
//   marker hover) lives here; only the resolved `cursorTs` + "is live"
//   boolean bubble up to the parent.

import { useMemo, useRef } from "react";

import type {
  TimelineConflict,
  TimelineDecision,
  TimelineResponse,
  TimelineTransition,
} from "@/lib/api";
import { formatIso } from "@/lib/time";

// Color tokens — match the existing severity palette on the canvas so
// markers and node tints speak the same visual language.
const SEVERITY_TINT: Record<string, string> = {
  critical: "#2563eb",
  high: "#2563eb",
  medium: "#c68a00",
  low: "#9a9a95",
};

// Normalized x for a given timestamp within [startMs, endMs]. Clamped to
// [0, 1] so markers authored slightly after `now` (clock race between
// the markers fetch and the `now` stamp) still render on the right edge.
function xFromTs(tsMs: number, startMs: number, endMs: number): number {
  if (endMs <= startMs) return 1;
  const raw = (tsMs - startMs) / (endMs - startMs);
  return Math.max(0, Math.min(1, raw));
}

// Round-trip a slider percentage (0..1) to an ISO-8601 timestamp in the
// project's timeline. We go through ms so no timezone surprises.
function tsFromX(x: number, startMs: number, endMs: number): string {
  const ms = Math.round(startMs + x * (endMs - startMs));
  return new Date(ms).toISOString();
}

interface Marker {
  id: string;
  x: number; // normalized 0..1
  ts: string;
  kind: "decision" | "conflict" | "transition";
  color: string;
  label: string;
}

function buildMarkers(
  timeline: TimelineResponse,
  startMs: number,
  endMs: number,
): Marker[] {
  const out: Marker[] = [];
  // Decisions — accent color, labeled with a truncated rationale.
  for (const d of timeline.decisions as TimelineDecision[]) {
    if (!d.created_at) continue;
    const ms = Date.parse(d.created_at);
    if (Number.isNaN(ms)) continue;
    out.push({
      id: `decision-${d.id}`,
      x: xFromTs(ms, startMs, endMs),
      ts: d.created_at,
      kind: "decision",
      color: "var(--wg-accent)",
      label: d.rationale || "Decision",
    });
  }
  // Conflicts — severity-tinted.
  for (const c of timeline.conflicts as TimelineConflict[]) {
    if (!c.created_at) continue;
    const ms = Date.parse(c.created_at);
    if (Number.isNaN(ms)) continue;
    out.push({
      id: `conflict-${c.id}`,
      x: xFromTs(ms, startMs, endMs),
      ts: c.created_at,
      kind: "conflict",
      color:
        SEVERITY_TINT[(c.severity || "low").toLowerCase()] ?? SEVERITY_TINT.low,
      label: `Conflict: ${c.rule}`,
    });
  }
  // Status transitions — ink-soft so they don't overwhelm the strip
  // when there are many.
  for (const tr of timeline.transitions as TimelineTransition[]) {
    const ms = Date.parse(tr.changed_at);
    if (Number.isNaN(ms)) continue;
    out.push({
      id: `transition-${tr.id}`,
      x: xFromTs(ms, startMs, endMs),
      ts: tr.changed_at,
      kind: "transition",
      color: "var(--wg-ink-soft)",
      label: `${tr.entity_kind} → ${tr.new_status}`,
    });
  }
  return out;
}

export interface TimelineStripLabels {
  live: string;
  asOf: string;
  playhead: string;
  markerDecision: string;
  markerConflict: string;
  markerTransition: string;
}

interface TimelineStripProps {
  timeline: TimelineResponse | null;
  cursorTs: string | null; // null = live
  onChange: (ts: string | null) => void; // null = snap back to live
  labels: TimelineStripLabels;
}

export function TimelineStrip({
  timeline,
  cursorTs,
  onChange,
  labels,
}: TimelineStripProps) {
  const trackRef = useRef<HTMLDivElement>(null);

  // Bounds + markers are recomputed only when the timeline payload
  // changes — rebuilding on every cursor drag would be wasteful.
  const { startMs, endMs, markers } = useMemo(() => {
    if (!timeline) {
      return { startMs: 0, endMs: 0, markers: [] as Marker[] };
    }
    const s = Date.parse(timeline.created_at);
    const e = Date.parse(timeline.now);
    if (Number.isNaN(s) || Number.isNaN(e)) {
      return { startMs: 0, endMs: 0, markers: [] as Marker[] };
    }
    return { startMs: s, endMs: e, markers: buildMarkers(timeline, s, e) };
  }, [timeline]);

  if (!timeline || endMs <= startMs) {
    return null;
  }

  // Normalized position of the playhead. Live mode sits at the right
  // edge (x=1); explicit cursor maps through xFromTs.
  const cursorX = cursorTs
    ? xFromTs(Date.parse(cursorTs), startMs, endMs)
    : 1;
  const isLive = cursorTs === null;

  // Click-to-scrub on the track. The parent fetches /graph-at when
  // the new ts differs from the previous one.
  const handleTrackClick = (ev: React.MouseEvent<HTMLDivElement>) => {
    const rect = (trackRef.current ?? ev.currentTarget).getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
    onChange(tsFromX(x, startMs, endMs));
  };

  // Range input wraps the pointer math so keyboard users get arrow-key
  // nudging for free. We use 0..1000 ticks so each tick is ~0.1% of
  // the span.
  const handleRangeChange = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const frac = Number(ev.target.value) / 1000;
    onChange(tsFromX(frac, startMs, endMs));
  };

  const formatted = cursorTs
    ? formatIso(cursorTs)
    : formatIso(endMs);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 14px",
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        color: "var(--wg-ink-soft)",
      }}
    >
      <button
        type="button"
        onClick={() => onChange(null)}
        disabled={isLive}
        style={{
          padding: "4px 10px",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          background: isLive ? "var(--wg-accent)" : "transparent",
          color: isLive ? "#fff" : "var(--wg-ink-soft)",
          border: `1px solid ${isLive ? "var(--wg-accent)" : "var(--wg-line)"}`,
          borderRadius: 4,
          cursor: isLive ? "default" : "pointer",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          transition: "background 140ms ease-out, color 140ms ease-out",
        }}
      >
        <span
          aria-hidden
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: 3,
            marginRight: 6,
            background: isLive ? "#fff" : "var(--wg-ink-faint)",
            verticalAlign: 1,
          }}
        />
        {labels.live}
      </button>

      <div
        ref={trackRef}
        role="presentation"
        onClick={handleTrackClick}
        style={{
          position: "relative",
          flex: 1,
          height: 28,
          cursor: "pointer",
          // The track is a thin line with markers on top — keeps the
          // strip visually quiet when no interaction is happening.
        }}
      >
        {/* Base line */}
        <div
          aria-hidden
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: "50%",
            transform: "translateY(-50%)",
            height: 2,
            background: "var(--wg-line)",
            borderRadius: 1,
          }}
        />
        {/* Progress fill — from left edge to cursor */}
        <div
          aria-hidden
          style={{
            position: "absolute",
            left: 0,
            width: `${cursorX * 100}%`,
            top: "50%",
            transform: "translateY(-50%)",
            height: 2,
            background: isLive ? "var(--wg-accent)" : "var(--wg-ink-faint)",
            borderRadius: 1,
            transition: "width 140ms ease-out",
          }}
        />
        {/* Markers */}
        {markers.map((m) => (
          <button
            key={m.id}
            type="button"
            title={`${m.label} — ${formatIso(m.ts)}`}
            onClick={(ev) => {
              ev.stopPropagation();
              onChange(m.ts);
            }}
            aria-label={
              m.kind === "decision"
                ? labels.markerDecision
                : m.kind === "conflict"
                  ? labels.markerConflict
                  : labels.markerTransition
            }
            style={{
              position: "absolute",
              left: `calc(${m.x * 100}% - 4px)`,
              top: "50%",
              transform: "translateY(-50%)",
              width: 8,
              height: 8,
              borderRadius: 4,
              background: m.color,
              border: "none",
              padding: 0,
              cursor: "pointer",
              boxShadow: "0 0 0 1px rgba(255,255,255,0.9)",
            }}
          />
        ))}
        {/* Playhead */}
        <div
          aria-hidden
          style={{
            position: "absolute",
            left: `calc(${cursorX * 100}% - 1px)`,
            top: 2,
            bottom: 2,
            width: 2,
            background: isLive
              ? "var(--wg-accent)"
              : "var(--wg-ink)",
            borderRadius: 1,
            transition: "left 140ms ease-out",
          }}
        />
        {/* Hidden keyboard-accessible range input layered on top so
            arrow keys still nudge the cursor. Opacity 0 keeps it
            invisible but operable. */}
        <input
          type="range"
          min={0}
          max={1000}
          value={Math.round(cursorX * 1000)}
          onChange={handleRangeChange}
          aria-label={labels.playhead}
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 0,
            bottom: 0,
            width: "100%",
            opacity: 0,
            cursor: "pointer",
          }}
        />
      </div>

      <span
        style={{
          whiteSpace: "nowrap",
          color: isLive ? "var(--wg-ink-soft)" : "var(--wg-ink)",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {isLive ? null : <span>{labels.asOf} </span>}
        {formatted}
      </span>
    </div>
  );
}
