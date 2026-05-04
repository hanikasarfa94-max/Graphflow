import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { KbItemDetail as KbItemDetailT } from "@/lib/api";
import { formatIso } from "@/lib/time";

// Detail view for a single KB item. Server component — nothing to
// interact with except the "back" link, so no client JS.
//
// Raw content is rendered inside a <pre> with white-space: pre-wrap and
// word-break set, so arbitrary pasted content (commit messages, tribal
// knowledge notes, scraped wiki pages) is readable but CANNOT be
// rendered as HTML. That's intentional — ingested content is untrusted.
export async function KbItemDetail({
  projectId,
  item,
  licenseControl,
}: {
  projectId: string;
  item: KbItemDetailT;
  // Phase 3.A — rendered in the sidebar when the viewer is a project
  // owner. The server component composes it conditionally so
  // non-owners never ship the client bundle.
  licenseControl?: React.ReactNode;
}) {
  const t = await getTranslations();
  const cls =
    (item.classification_json ?? {}) as {
      summary?: string;
      confidence?: number;
      tags?: string[];
    };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <div>
        <Link
          href={`/projects/${projectId}/kb`}
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            textDecoration: "none",
          }}
        >
          {t("kb.item.back")}
        </Link>
      </div>

      <div
        style={{
          display: "grid",
          gap: 16,
          gridTemplateColumns: "minmax(0, 2fr) minmax(260px, 1fr)",
          alignItems: "start",
        }}
      >
        <section
          style={{
            minWidth: 0,
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            background: "#fff",
            padding: "16px 18px",
          }}
        >
          <h2
            style={{
              margin: 0,
              fontSize: 12,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wg-ink-soft)",
              fontWeight: 600,
              marginBottom: 10,
            }}
          >
            {item.source_kind || "kb"}
          </h2>
          {/* Title row — kb_items is the unified store; user-authored
              rows (save-as-kb / paste / upload) populate `title` +
              `content_md`, while ingest rows populate `raw_content` +
              `source_*`. Pick the first populated identifier so the
              page never renders as a blank slate. */}
          {(item.title || item.summary || item.source_identifier) && (
            <h3
              style={{
                margin: "0 0 12px 0",
                fontSize: 22,
                fontWeight: 600,
                lineHeight: 1.3,
                color: "var(--wg-ink)",
                fontFamily: "var(--wg-font-serif, Georgia, serif)",
              }}
            >
              {item.title || item.summary || item.source_identifier}
            </h3>
          )}
          {(item.content_md || item.raw_content) ? (
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontFamily:
                  "var(--wg-font-serif, Georgia, serif)",
                fontSize: 15,
                lineHeight: 1.55,
                color: "var(--wg-ink)",
                // Reset the default <pre> dark monospace look.
                background: "transparent",
              }}
            >
              {item.content_md || item.raw_content}
            </pre>
          ) : (
            <div
              data-testid="kb-item-empty-body"
              style={{
                fontSize: 13,
                color: "var(--wg-ink-soft)",
                padding: "20px 12px",
                border: "1px dashed var(--wg-line)",
                borderRadius: "var(--wg-radius)",
                textAlign: "center",
                fontStyle: "italic",
              }}
            >
              {t("kb.item.emptyBody")}
            </div>
          )}
        </section>

        <aside
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            minWidth: 0,
          }}
        >
          <MetaPanel title={t("kb.item.source")}>
            <div
              style={{
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
                marginBottom: 4,
              }}
            >
              {item.source_kind}
            </div>
            {item.source_identifier ? (
              isHttpUrl(item.source_identifier) ? (
                <a
                  href={item.source_identifier}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    fontSize: 13,
                    color: "var(--wg-link, #155bd5)",
                    wordBreak: "break-all",
                    textDecoration: "underline",
                  }}
                >
                  {item.source_identifier}
                </a>
              ) : (
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--wg-ink)",
                    wordBreak: "break-all",
                    fontFamily: "var(--wg-font-mono)",
                  }}
                >
                  {item.source_identifier}
                </div>
              )
            ) : (
              <div
                style={{
                  fontSize: 12,
                  color: "var(--wg-ink-soft)",
                  fontStyle: "italic",
                }}
              >
                —
              </div>
            )}
          </MetaPanel>

          <MetaPanel title={t("kb.item.classification")}>
            {item.summary ? (
              <div
                style={{
                  fontSize: 13,
                  color: "var(--wg-ink)",
                  lineHeight: 1.5,
                  marginBottom: 8,
                }}
              >
                {item.summary}
              </div>
            ) : null}
            {item.tags && item.tags.length > 0 ? (
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 4,
                  marginBottom: 8,
                }}
              >
                {item.tags.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      fontSize: 10,
                      fontFamily: "var(--wg-font-mono)",
                      padding: "1px 6px",
                      background: "var(--wg-surface)",
                      border: "1px solid var(--wg-line)",
                      borderRadius: 10,
                      color: "var(--wg-ink-soft)",
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
            {typeof cls.confidence === "number" ? (
              <div
                style={{
                  fontSize: 11,
                  fontFamily: "var(--wg-font-mono)",
                  color: "var(--wg-ink-soft)",
                }}
              >
                confidence {cls.confidence.toFixed(2)}
              </div>
            ) : null}
          </MetaPanel>

          <MetaPanel title={t("kb.item.ingestedBy")}>
            <div
              style={{
                fontSize: 13,
                color: "var(--wg-ink)",
              }}
            >
              {item.ingested_by_username
                ? `@${item.ingested_by_username}`
                : "—"}
            </div>
            <div
              style={{
                fontSize: 11,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
                marginTop: 4,
              }}
            >
              {formatIso(item.created_at)}
            </div>
          </MetaPanel>

          <MetaPanel title={t("kb.item.status")}>
            <div
              style={{
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink)",
              }}
            >
              {item.status}
            </div>
            {item.status === "draft" || item.status === "pending-review" ? (
              // The detail page is read-only by design (no inline
              // approve buttons — that lives in /detail/im, the
              // single membrane review surface). Surface the link
              // here so a reader who lands on a draft via the chip
              // knows where to act.
              <Link
                href={`/projects/${projectId}/detail/im`}
                style={{
                  display: "inline-block",
                  marginTop: 6,
                  fontSize: 11,
                  fontFamily: "var(--wg-font-mono)",
                  color: "var(--wg-accent)",
                  textDecoration: "none",
                }}
              >
                {t("kb.item.reviewLink")}
              </Link>
            ) : null}
          </MetaPanel>

          {licenseControl}
        </aside>
      </div>
    </div>
  );
}

function MetaPanel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section
      style={{
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "#fff",
        padding: "10px 12px",
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wg-ink-soft)",
          fontWeight: 600,
          marginBottom: 6,
        }}
      >
        {title}
      </div>
      {children}
    </section>
  );
}

function isHttpUrl(s: string): boolean {
  return /^https?:\/\//i.test(s);
}
