"use client";

// Client half of /projects/[id]/renders/[slug].
//
// Receives an initial RenderedArtifact (fetched server-side) and handles:
//   - Regenerate button → POST the regenerate endpoint, swap state.
//   - Lightly-edit-a-section → local textarea, state-only (v1 note: not
//     persisted; the server render is the source of truth on reload).
//   - Decision-id citation linking → `**D-<id>**` in bodies turns into
//     `/projects/[id]/nodes/<id>` anchors when `decisionIds` recognizes
//     the id; otherwise stays plain text.
//
// Markdown rendering is a tiny in-file function — we deliberately avoid
// adding react-markdown since the LLM output is constrained (bullets,
// bold, italic, links) and the prompt contract forbids HTML + tables.
// If the rendered output needs more Markdown features later, swap in
// react-markdown here without touching the rest of the flow.

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import {
  regenerateHandoffRender,
  regeneratePostmortemRender,
  type HandoffRender,
  type PostmortemRender,
  type RenderedSection,
} from "@/lib/api";
import { classifyEdit, type EditSignal } from "@/lib/editSignal";
import {
  EditSignalModal,
  type EditSignalResult,
} from "@/components/rendered/EditSignalModal";
import { formatIso } from "@/lib/time";

type AnyRender = PostmortemRender | HandoffRender;

export function RenderView({
  projectId,
  slug,
  initial,
  decisionIds,
  isPostmortem,
}: {
  projectId: string;
  slug: string;
  initial: AnyRender;
  // Set of real decision ids so we can link `**D-<id>**` citations.
  decisionIds: string[];
  isPostmortem: boolean;
}) {
  const t = useTranslations();
  const [render, setRender] = useState<AnyRender>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Per-section local edits — keyed by section index. Not persisted.
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  // Modal state for the edit-signal ceremony. We snapshot the before/
  // after text into the modal's props so later keystrokes (if any leak
  // through the disabled editor) can't shift the classification mid-
  // prompt.
  const [signalModal, setSignalModal] = useState<{
    idx: number;
    before: string;
    after: string;
    signal: EditSignal;
  } | null>(null);

  const realIds = useMemo(() => new Set(decisionIds), [decisionIds]);

  // Save path for an edited section. Runs the heuristic classifier;
  // high-confidence prose polish saves silently (matches the
  // pre-feature behavior), everything else opens the modal so the
  // human chooses what the edit *means*. See docs/north-star.md on why
  // this ceremony is load-bearing.
  function handleSaveSection(idx: number) {
    const original = doc.sections[idx]?.body_markdown ?? "";
    const edited = edits[idx] ?? original;
    // No-op save — close the editor and move on. Avoids opening a
    // modal for an edit the user immediately reverted.
    if (edited === original) {
      setEditingIdx(null);
      return;
    }
    const signal = classifyEdit(original, edited);
    if (signal.kind === "prose_polish" && signal.confidence > 0.8) {
      // Silent path — v1 "save" is just committing local state.
      setEditingIdx(null);
      return;
    }
    setSignalModal({ idx, before: original, after: edited, signal });
  }

  function handleSignalResolve(result: EditSignalResult | null) {
    const pending = signalModal;
    setSignalModal(null);
    if (!result || !pending) {
      // Cancel — keep the editor open so the user can keep typing or
      // cancel-cancel via the editor's own Cancel button.
      return;
    }
    // v2 TODO: POST the classification + chosen action to the backend
    // edit-signal endpoint so the edge LLM can crystallize a decision
    // / risk / cascade on our behalf. v1 emits to the console so the
    // ceremony is demo-visible without backend changes.
    // eslint-disable-next-line no-console
    console.log("[editSignal] v1 stub", {
      projectId,
      slug,
      sectionIdx: pending.idx,
      kind: result.signal.kind,
      action: result.action,
      confidence: result.signal.confidence,
      matchedSignals: result.signal.matchedSignals,
    });
    setEditingIdx(null);
  }

  async function regenerate() {
    setBusy(true);
    setError(null);
    try {
      if (isPostmortem) {
        const next = await regeneratePostmortemRender(projectId);
        setRender(next);
      } else {
        // Handoff slug: handoff:<user_id>
        const userId = slug.slice("handoff:".length);
        const next = await regenerateHandoffRender(projectId, userId);
        setRender(next);
      }
      setEdits({});
      setEditingIdx(null);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "regenerate failed";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  const doc = render.doc;
  const generatedAt = formatIso(render.generated_at);

  return (
    <main
      // Generous horizontal padding (clamp(24px, 5vw, 56px)) so titles
      // and prose never sit flush against the AppShell main-column
      // edge, regardless of viewport width. The previous 24px felt
      // tight on wide screens (the report read as edge-locked) and
      // collapsed even further when the legacy AppSidebar took its
      // 240px from a sub-1024px viewport. clamp() keeps it readable
      // on tablets while letting wide screens breathe.
      style={{
        maxWidth: 760,
        margin: "0 auto",
        padding: "48px clamp(24px, 5vw, 56px) 64px",
        fontFamily: "var(--wg-font-serif, Georgia, serif)",
        color: "var(--wg-ink, #0a1a2b)",
        lineHeight: 1.6,
      }}
    >
      <header style={{ marginBottom: 32 }}>
        <h1
          style={{
            fontSize: 30,
            fontWeight: 700,
            margin: "0 0 8px",
            letterSpacing: "-0.01em",
          }}
        >
          {doc.title}
        </h1>
        {"one_line_summary" in doc && doc.one_line_summary ? (
          <p
            style={{
              fontSize: 16,
              color: "var(--wg-ink-soft, #4b6075)",
              fontStyle: "italic",
              margin: "0 0 16px",
            }}
          >
            {doc.one_line_summary}
          </p>
        ) : null}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            fontSize: 12,
            fontFamily: "var(--wg-font-mono, ui-monospace, monospace)",
            color: "var(--wg-ink-soft, #4b6075)",
            borderTop: "1px solid var(--wg-line-soft, #e6ebf1)",
            borderBottom: "1px solid var(--wg-line-soft, #e6ebf1)",
            padding: "8px 0",
          }}
        >
          <span>{t("render.generatedAt", { time: generatedAt })}</span>
          <button
            onClick={regenerate}
            disabled={busy}
            style={{
              marginLeft: "auto",
              background: "transparent",
              border: "1px solid var(--wg-line, #d6dde6)",
              padding: "4px 10px",
              fontSize: 12,
              fontFamily: "inherit",
              cursor: busy ? "wait" : "pointer",
              color: "var(--wg-ink, #0a1a2b)",
              borderRadius: 2,
            }}
          >
            {busy ? t("render.regenerating") : t("render.regenerate")}
          </button>
        </div>
        {render.outcome === "manual_review" ? (
          <p
            role="status"
            style={{
              marginTop: 12,
              padding: "8px 12px",
              background: "var(--wg-warn-soft, #fff4d6)",
              border: "1px solid var(--wg-warn, #c79c00)",
              fontSize: 13,
              fontFamily: "var(--wg-font-mono, ui-monospace, monospace)",
              color: "var(--wg-ink, #0a1a2b)",
            }}
          >
            {t("render.manualReview")}
          </p>
        ) : null}
        {error ? (
          <p
            role="alert"
            style={{
              marginTop: 12,
              color: "var(--wg-accent, #c03030)",
              fontSize: 13,
            }}
          >
            {error}
          </p>
        ) : null}
      </header>

      {doc.sections.map((section: RenderedSection, idx: number) => {
        const isEditing = editingIdx === idx;
        const body = edits[idx] ?? section.body_markdown;
        return (
          <section
            key={idx}
            style={{ marginBottom: 36 }}
            aria-labelledby={`render-section-${idx}`}
          >
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 12,
                marginBottom: 8,
              }}
            >
              <h2
                id={`render-section-${idx}`}
                style={{
                  fontSize: 20,
                  fontWeight: 600,
                  margin: 0,
                  letterSpacing: "-0.005em",
                }}
              >
                {section.heading}
              </h2>
              <button
                onClick={() =>
                  setEditingIdx((cur) => (cur === idx ? null : idx))
                }
                style={{
                  marginLeft: "auto",
                  background: "transparent",
                  border: "none",
                  color: "var(--wg-ink-soft, #4b6075)",
                  fontSize: 11,
                  fontFamily: "var(--wg-font-mono, ui-monospace, monospace)",
                  cursor: "pointer",
                  padding: 2,
                }}
                aria-expanded={isEditing}
              >
                {isEditing ? t("render.cancelEdit") : t("render.editSection")}
              </button>
            </div>
            {isEditing ? (
              <div>
                <textarea
                  value={body}
                  onChange={(e) =>
                    setEdits((cur) => ({ ...cur, [idx]: e.target.value }))
                  }
                  rows={Math.max(6, body.split("\n").length + 2)}
                  style={{
                    width: "100%",
                    fontFamily:
                      "var(--wg-font-mono, ui-monospace, monospace)",
                    fontSize: 13,
                    padding: 10,
                    lineHeight: 1.55,
                    border: "1px solid var(--wg-line, #d6dde6)",
                    color: "var(--wg-ink, #0a1a2b)",
                    background: "var(--wg-paper, #ffffff)",
                  }}
                />
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginTop: 6,
                    fontSize: 11,
                    color: "var(--wg-ink-soft, #4b6075)",
                    fontFamily: "var(--wg-font-mono, ui-monospace, monospace)",
                  }}
                >
                  <span>{t("render.editNote")}</span>
                  <button
                    onClick={() => handleSaveSection(idx)}
                    style={{
                      background: "var(--wg-ink, #0a1a2b)",
                      color: "var(--wg-paper, #ffffff)",
                      border: "none",
                      padding: "4px 10px",
                      fontSize: 12,
                      fontFamily: "inherit",
                      cursor: "pointer",
                      borderRadius: 2,
                    }}
                  >
                    {t("render.saveSection")}
                  </button>
                </div>
              </div>
            ) : (
              <MarkdownBody
                markdown={body}
                projectId={projectId}
                realDecisionIds={realIds}
              />
            )}
          </section>
        );
      })}
      <EditSignalModal
        open={signalModal !== null}
        signal={signalModal?.signal ?? null}
        before={signalModal?.before ?? ""}
        after={signalModal?.after ?? ""}
        onResolve={handleSignalResolve}
      />
    </main>
  );
}

// ---------------------------------------------------------------------
// Tiny-but-safe markdown renderer.
// ---------------------------------------------------------------------
// Handles the CommonMark subset the prompts promise:
//   - `#`/`##`/`###` headings (rare — top-level h2s come from sections)
//   - `-` bulleted lists (one-level; the prompts don't produce nested)
//   - `> blockquote`
//   - blank line → paragraph break
//   - inline `**bold**`, `*italic*`, `[text](url)`
//   - `**D-<id>**` bold that matches a real decision id becomes a Link
//     into `/projects/[id]/nodes/<id>`.
//
// Everything that would be HTML gets rendered as plain text — no
// `dangerouslySetInnerHTML`. That's deliberate: LLM output is input, and
// user-reachable pages must not turn arbitrary rendered markdown into
// HTML without a sanitizer. This path has none because we never emit
// HTML in the first place.
function MarkdownBody({
  markdown,
  projectId,
  realDecisionIds,
}: {
  markdown: string;
  projectId: string;
  realDecisionIds: Set<string>;
}) {
  const blocks = useMemo(() => parseBlocks(markdown), [markdown]);
  return (
    <div style={{ fontSize: 16 }}>
      {blocks.map((block, i) => {
        if (block.kind === "heading") {
          // All inline section-subheadings render as h3 — the outer
          // <section> already provides its own h2 from `section.heading`.
          // React 19 dropped the JSX-namespace globals, so we render
          // directly rather than parameterizing on a tag name.
          return (
            <h3
              key={i}
              style={{
                fontSize: 16,
                fontWeight: 600,
                margin: "18px 0 8px",
              }}
            >
              {renderInline(block.text, projectId, realDecisionIds)}
            </h3>
          );
        }
        if (block.kind === "list") {
          return (
            <ul
              key={i}
              style={{
                paddingLeft: 20,
                margin: "8px 0",
              }}
            >
              {block.items.map((item, j) => (
                <li key={j} style={{ margin: "4px 0" }}>
                  {renderInline(item, projectId, realDecisionIds)}
                </li>
              ))}
            </ul>
          );
        }
        if (block.kind === "quote") {
          return (
            <blockquote
              key={i}
              style={{
                borderLeft:
                  "3px solid var(--wg-line, #d6dde6)",
                paddingLeft: 12,
                color: "var(--wg-ink-soft, #4b6075)",
                margin: "8px 0",
                fontStyle: "italic",
              }}
            >
              {renderInline(block.text, projectId, realDecisionIds)}
            </blockquote>
          );
        }
        return (
          <p key={i} style={{ margin: "10px 0" }}>
            {renderInline(block.text, projectId, realDecisionIds)}
          </p>
        );
      })}
    </div>
  );
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "quote"; text: string }
  | { kind: "para"; text: string };

function parseBlocks(md: string): Block[] {
  const lines = md.split(/\r?\n/);
  const blocks: Block[] = [];
  let paraBuf: string[] = [];
  let listBuf: string[] | null = null;
  const flushPara = () => {
    if (paraBuf.length) {
      blocks.push({ kind: "para", text: paraBuf.join(" ") });
      paraBuf = [];
    }
  };
  const flushList = () => {
    if (listBuf && listBuf.length) {
      blocks.push({ kind: "list", items: listBuf });
    }
    listBuf = null;
  };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }
    const headingMatch = /^(#{1,3})\s+(.*)$/.exec(line);
    if (headingMatch) {
      flushPara();
      flushList();
      blocks.push({
        kind: "heading",
        level: headingMatch[1].length,
        text: headingMatch[2],
      });
      continue;
    }
    const bullet = /^[-*+]\s+(.*)$/.exec(line);
    if (bullet) {
      flushPara();
      if (!listBuf) listBuf = [];
      listBuf.push(bullet[1]);
      continue;
    }
    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) {
      flushPara();
      flushList();
      blocks.push({ kind: "quote", text: quote[1] });
      continue;
    }
    flushList();
    paraBuf.push(line);
  }
  flushPara();
  flushList();
  return blocks;
}

// Inline-markdown renderer. Produces an array of React nodes — strings +
// <strong>/<em>/<a>/<Link> elements. Order of precedence:
//   1) decision-id link token  `**D-<id>**`
//   2) markdown link            `[text](url)`
//   3) bold                     `**text**`
//   4) italic                   `*text*`
//
// Each rule splits the remaining text and recurses into the non-matching
// surroundings. We cap recursion depth implicitly by always removing the
// matched segment before recursing.
function renderInline(
  text: string,
  projectId: string,
  realDecisionIds: Set<string>,
): React.ReactNode[] {
  // 1. Decision-id citation.
  const decisionRe = /\*\*D-([A-Za-z0-9_\-]+)\*\*/;
  const decisionMatch = decisionRe.exec(text);
  if (decisionMatch) {
    const id = decisionMatch[1];
    const before = text.slice(0, decisionMatch.index);
    const after = text.slice(decisionMatch.index + decisionMatch[0].length);
    const isReal = realDecisionIds.has(id);
    return [
      ...renderInline(before, projectId, realDecisionIds),
      isReal ? (
        <Link
          key={`d-${decisionMatch.index}-${id}`}
          href={`/projects/${projectId}/nodes/${id}`}
          style={{
            fontWeight: 600,
            color: "var(--wg-link, #155bd5)",
            textDecoration: "underline",
          }}
        >
          D-{id}
        </Link>
      ) : (
        <strong key={`d-${decisionMatch.index}-${id}`}>D-{id}</strong>
      ),
      ...renderInline(after, projectId, realDecisionIds),
    ];
  }
  // 2. Markdown link.
  const linkRe = /\[([^\]]+)\]\(([^)]+)\)/;
  const linkMatch = linkRe.exec(text);
  if (linkMatch) {
    const before = text.slice(0, linkMatch.index);
    const after = text.slice(linkMatch.index + linkMatch[0].length);
    return [
      ...renderInline(before, projectId, realDecisionIds),
      <a
        key={`l-${linkMatch.index}`}
        href={linkMatch[2]}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: "var(--wg-link, #155bd5)",
          textDecoration: "underline",
        }}
      >
        {linkMatch[1]}
      </a>,
      ...renderInline(after, projectId, realDecisionIds),
    ];
  }
  // 3. Bold.
  const boldRe = /\*\*([^*]+)\*\*/;
  const boldMatch = boldRe.exec(text);
  if (boldMatch) {
    const before = text.slice(0, boldMatch.index);
    const after = text.slice(boldMatch.index + boldMatch[0].length);
    return [
      ...renderInline(before, projectId, realDecisionIds),
      <strong key={`b-${boldMatch.index}`}>{boldMatch[1]}</strong>,
      ...renderInline(after, projectId, realDecisionIds),
    ];
  }
  // 4. Italic (single-star, not already-consumed bold).
  const italicRe = /(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/;
  const italicMatch = italicRe.exec(text);
  if (italicMatch) {
    const prefix = italicMatch[1];
    const inner = italicMatch[2];
    const start = italicMatch.index + prefix.length;
    const end = start + inner.length + 2; // includes the two stars
    const before = text.slice(0, start);
    const after = text.slice(end);
    return [
      ...renderInline(before, projectId, realDecisionIds),
      <em key={`i-${start}`}>{inner}</em>,
      ...renderInline(after, projectId, realDecisionIds),
    ];
  }
  return [text];
}
