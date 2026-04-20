import { cookies, headers } from "next/headers";
import Link from "next/link";

import { requireUser } from "@/lib/auth";
import {
  PROFILE_OBSERVED_KEYS,
  type ProfileTallies,
  fetchMyProfile,
  pickLocale,
  profileMessages,
} from "@/lib/profile";

export const dynamic = "force-dynamic";

// Server-side base URL — matches lib/auth.ts so dev + Docker both work.
const API_BASE =
  process.env.WORKGRAPH_API_BASE_SERVER ??
  process.env.WORKGRAPH_API_BASE ??
  "http://127.0.0.1:8000";

function formatTimestamp(value: string | null, locale: string): string | null {
  if (!value) return null;
  try {
    // Locale-aware; stable for server rendering because we pass an explicit
    // locale rather than letting the runtime pick "system default".
    return new Date(value).toLocaleString(locale === "zh" ? "zh-CN" : "en-US");
  } catch {
    return value;
  }
}

export default async function SettingsProfilePage() {
  const user = await requireUser("/settings/profile");
  const cookieHeader = (await cookies()).toString();
  const hdrs = await headers();
  const locale = pickLocale(hdrs.get("accept-language"));
  const t = profileMessages(locale);

  const tallies: ProfileTallies | null = await fetchMyProfile(
    API_BASE,
    cookieHeader,
  );

  const observed = tallies?.observed ?? {
    messages_posted_7d: 0,
    messages_posted_30d: 0,
    decisions_resolved_30d: 0,
    routings_answered_30d: 0,
    risks_owned: 0,
    projects_active: 0,
  };
  const roleCounts = tallies?.role_counts ?? {};
  const lastActivityFormatted = formatTimestamp(
    tallies?.last_activity_at ?? null,
    locale,
  );

  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "56px 24px",
        fontFamily: "var(--wg-font-sans)",
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 24,
          gap: 16,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wg-ink-soft)",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: "var(--wg-dot)",
                height: "var(--wg-dot)",
                borderRadius: "50%",
                background: "var(--wg-accent)",
                marginRight: 8,
                verticalAlign: "middle",
              }}
            />
            WorkGraph · <Link href="/projects">projects</Link>
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 600, margin: "8px 0 0" }}>
            {t.title}
          </h1>
          <p
            style={{
              margin: "6px 0 0",
              color: "var(--wg-ink-soft)",
              fontSize: 14,
              maxWidth: 520,
            }}
          >
            {t.subtitle}
          </p>
        </div>
        <div
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            textAlign: "right",
          }}
        >
          {user.display_name}
          <form
            action="/api/auth/logout?redirect=/"
            method="POST"
            style={{ display: "inline" }}
          >
            <button
              type="submit"
              style={{
                marginLeft: 10,
                background: "transparent",
                border: "none",
                color: "var(--wg-accent)",
                cursor: "pointer",
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t.signOut}
            </button>
          </form>
        </div>
      </header>

      {/* Self-declared section lives above — kept as a placeholder until
          the ability catalog ships. The observed block below is the
          compute-on-read projection. */}

      <section
        aria-labelledby="observed-heading"
        style={{
          marginTop: 24,
          padding: 20,
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
        }}
      >
        <h2
          id="observed-heading"
          style={{
            fontSize: 16,
            fontWeight: 600,
            margin: 0,
            marginBottom: 4,
          }}
        >
          {t.observedSectionHeading}
        </h2>

        {/* Stats grid — 2 cols, labels + numbers. */}
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "12px 24px",
            margin: "16px 0 12px",
            padding: 0,
          }}
        >
          {PROFILE_OBSERVED_KEYS.map((key) => (
            <div
              key={key}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                borderBottom: "1px solid var(--wg-line-soft)",
                paddingBottom: 8,
              }}
            >
              <dt
                style={{
                  fontSize: 13,
                  color: "var(--wg-ink-soft)",
                  margin: 0,
                }}
              >
                {t.observedLabels[key]}
              </dt>
              <dd
                style={{
                  fontFamily: "var(--wg-font-mono)",
                  fontSize: 18,
                  fontWeight: 600,
                  margin: 0,
                  color: "var(--wg-ink)",
                }}
              >
                {observed[key]}
              </dd>
            </div>
          ))}
        </dl>

        <p
          style={{
            fontSize: 12,
            color: "var(--wg-ink-faint)",
            margin: 0,
          }}
        >
          {t.observedFootnote}
        </p>

        <div
          style={{
            marginTop: 16,
            paddingTop: 12,
            borderTop: "1px solid var(--wg-line-soft)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            fontSize: 13,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          <span>{t.lastActivityLabel}</span>
          <span style={{ color: "var(--wg-ink)" }}>
            {lastActivityFormatted ?? t.lastActivityNever}
          </span>
        </div>
      </section>

      <section
        aria-labelledby="roles-heading"
        style={{
          marginTop: 20,
          padding: 20,
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
        }}
      >
        <h2
          id="roles-heading"
          style={{
            fontSize: 16,
            fontWeight: 600,
            margin: 0,
            marginBottom: 8,
          }}
        >
          {t.rolesHeading}
        </h2>
        {Object.keys(roleCounts).length === 0 ? (
          <p
            style={{
              margin: 0,
              color: "var(--wg-ink-soft)",
              fontSize: 13,
            }}
          >
            {t.rolesEmpty}
          </p>
        ) : (
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            {Object.entries(roleCounts).map(([role, n]) => (
              <li
                key={role}
                style={{
                  padding: "4px 10px",
                  borderRadius: 999,
                  background: "var(--wg-accent-soft)",
                  color: "var(--wg-accent)",
                  fontFamily: "var(--wg-font-mono)",
                  fontSize: 12,
                }}
              >
                {role} · {n}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
