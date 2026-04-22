import { cookies, headers } from "next/headers";
import Link from "next/link";

import { ReplayButton } from "@/components/onboarding/ReplayButton";
import { Button, Card, Heading, Text } from "@/components/ui";
import type { ProjectSummary } from "@/lib/api";
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

  // Phase 1.B — "Replay onboarding" surface per project. We fetch the
  // user's project list so each row can independently reset its
  // OnboardingStateRow. Best-effort: if the list call fails we just
  // hide the block.
  let myProjects: ProjectSummary[] = [];
  try {
    const res = await fetch(`${API_BASE}/api/projects`, {
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
      cache: "no-store",
    });
    if (res.ok) {
      myProjects = (await res.json()) as ProjectSummary[];
    }
  } catch {
    myProjects = [];
  }

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
          <Text
            as="div"
            variant="label"
            muted
            style={{
              letterSpacing: "0.08em",
              textTransform: "uppercase",
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
          </Text>
          <Heading level={1} style={{ margin: "8px 0 0" }}>
            {t.title}
          </Heading>
          <Text
            as="p"
            variant="body"
            muted
            style={{ margin: "6px 0 0", maxWidth: 520 }}
          >
            {t.subtitle}
          </Text>
        </div>
        <div style={{ textAlign: "right" }}>
          <Text variant="label" muted style={{ fontFamily: "var(--wg-font-mono)" }}>
            {user.display_name}
          </Text>
          <form
            action="/api/auth/logout?redirect=/"
            method="POST"
            style={{ display: "inline" }}
          >
            <Button
              type="submit"
              variant="link"
              size="sm"
              style={{ marginLeft: 10 }}
            >
              {t.signOut}
            </Button>
          </form>
        </div>
      </header>

      {/* Self-declared section lives above — kept as a placeholder until
          the ability catalog ships. The observed block below is the
          compute-on-read projection. */}

      <Card variant="raised" style={{ marginTop: 24 }} aria-labelledby="observed-heading">
        <Heading
          level={2}
          id="observed-heading"
          style={{ marginBottom: 4 }}
        >
          {t.observedSectionHeading}
        </Heading>

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
              <Text as="dt" variant="body" muted>
                {t.observedLabels[key]}
              </Text>
              <Text
                as="dd"
                variant="mono"
                style={{ fontSize: 18, fontWeight: 600 }}
              >
                {observed[key]}
              </Text>
            </div>
          ))}
        </dl>

        <Text
          as="p"
          variant="label"
          style={{ color: "var(--wg-ink-faint)" }}
        >
          {t.observedFootnote}
        </Text>

        <div
          style={{
            marginTop: 16,
            paddingTop: 12,
            borderTop: "1px solid var(--wg-line-soft)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
          }}
        >
          <Text variant="body" muted style={{ fontFamily: "var(--wg-font-mono)" }}>
            {t.lastActivityLabel}
          </Text>
          <Text variant="mono">
            {lastActivityFormatted ?? t.lastActivityNever}
          </Text>
        </div>
      </Card>

      <Card variant="raised" style={{ marginTop: 20 }} aria-labelledby="roles-heading">
        <Heading
          level={2}
          id="roles-heading"
          style={{ marginBottom: 8 }}
        >
          {t.rolesHeading}
        </Heading>
        {Object.keys(roleCounts).length === 0 ? (
          <Text as="p" variant="body" muted>
            {t.rolesEmpty}
          </Text>
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
                  fontSize: "var(--wg-fs-label)",
                }}
              >
                {role} · {n}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        variant="raised"
        style={{ marginTop: 20 }}
        aria-labelledby="onboarding-heading"
      >
        <Heading
          level={2}
          id="onboarding-heading"
          style={{ marginBottom: 4 }}
        >
          {t.onboardingHeading}
        </Heading>
        <Text as="p" variant="body" muted style={{ margin: "0 0 12px" }}>
          {t.onboardingBody}
        </Text>
        {myProjects.length === 0 ? (
          <Text as="p" variant="body" muted>
            {t.onboardingNoProjects}
          </Text>
        ) : (
          <div>
            {myProjects.map((p) => (
              <ReplayButton
                key={p.id}
                projectId={p.id}
                projectTitle={p.title}
                label={t.onboardingReplayButton}
              />
            ))}
          </div>
        )}
      </Card>
    </main>
  );
}
