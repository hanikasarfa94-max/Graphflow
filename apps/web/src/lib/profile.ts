// Observed-profile types + fetch helper for /settings/profile.
//
// Per docs/north-star.md §"Profile as first-class primitive", every user
// has a response profile combining self-declared abilities + observed
// emissions. This module models the *observed* half served by
// `GET /api/users/me/profile` (compute-on-read; no denorm columns).
//
// Kept separate from lib/api.ts so the profile surface can evolve (add
// self-declared, add derived scores) without rippling into the shared
// client shape.
import { ApiError } from "@/lib/api";

export interface ProfileObserved {
  messages_posted_7d: number;
  messages_posted_30d: number;
  decisions_resolved_30d: number;
  risks_owned: number;
  routings_answered_30d: number;
  projects_active: number;
}

export interface ProfileTallies {
  user_id: string;
  display_name: string;
  role_counts: Record<string, number>;
  observed: ProfileObserved;
  last_activity_at: string | null;
}

export const PROFILE_OBSERVED_KEYS: Array<keyof ProfileObserved> = [
  "messages_posted_7d",
  "messages_posted_30d",
  "decisions_resolved_30d",
  "routings_answered_30d",
  "risks_owned",
  "projects_active",
];

// Server-side fetch — forwards the session cookie so the FastAPI auth
// guard sees the signed-in user. Returns null on 401 so the caller can
// fall back to a logged-out placeholder without a redirect loop.
export async function fetchMyProfile(
  baseUrl: string,
  cookieHeader: string,
): Promise<ProfileTallies | null> {
  const res = await fetch(`${baseUrl}/api/users/me/profile`, {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    cache: "no-store",
  });
  if (res.status === 401) return null;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, body, `profile ${res.status}`);
  }
  return body as ProfileTallies;
}

// ---------- i18n ----------
// No next-intl in this build. We co-locate the ZH + EN strings here and
// pick by an explicit `locale` arg so the server component stays a
// single file. When next-intl lands, swap these for message keys
// rooted at `profile.*` — shape chosen to match the task spec.

export type Locale = "en" | "zh";

export interface ProfileMessages {
  title: string;
  subtitle: string;
  observedSectionHeading: string;
  observedFootnote: string;
  lastActivityLabel: string;
  lastActivityNever: string;
  rolesHeading: string;
  rolesEmpty: string;
  observedLabels: Record<keyof ProfileObserved, string>;
  signOut: string;
  // Phase 1.B — ambient onboarding replay section.
  onboardingHeading: string;
  onboardingBody: string;
  onboardingReplayButton: string;
  onboardingNoProjects: string;
}

const EN: ProfileMessages = {
  title: "Profile",
  subtitle:
    "Self-declared abilities + observed emissions. The observed half is rebuilt on every load from your activity.",
  observedSectionHeading: "Observed profile",
  observedFootnote:
    "Profile observations, rolling 30 days — updates in real time from your activity.",
  lastActivityLabel: "Last activity",
  lastActivityNever: "No recorded activity yet",
  rolesHeading: "Project roles",
  rolesEmpty: "Not a member of any project yet.",
  observedLabels: {
    messages_posted_7d: "Messages posted (7d)",
    messages_posted_30d: "Messages posted (30d)",
    decisions_resolved_30d: "Decisions resolved (30d)",
    routings_answered_30d: "Routings answered (30d)",
    risks_owned: "Open risks you own",
    projects_active: "Active projects",
  },
  signOut: "Sign out",
  onboardingHeading: "Onboarding",
  onboardingBody:
    "Re-open the Day 1 walkthrough on a project's next visit.",
  onboardingReplayButton: "Replay on this project",
  onboardingNoProjects: "Not a member of any project yet.",
};

const ZH: ProfileMessages = {
  title: "个人画像",
  subtitle:
    "自述能力 + 观察到的行为信号。观察部分在每次打开时根据你的活动重新计算。",
  observedSectionHeading: "观察到的画像",
  observedFootnote: "观察数据,30 天滚动窗口 — 随你的活动实时更新。",
  lastActivityLabel: "最近活跃",
  lastActivityNever: "暂无活动记录",
  rolesHeading: "项目角色",
  rolesEmpty: "尚未加入任何项目。",
  observedLabels: {
    messages_posted_7d: "近 7 天消息数",
    messages_posted_30d: "近 30 天消息数",
    decisions_resolved_30d: "近 30 天裁决数",
    routings_answered_30d: "近 30 天已回应派单",
    risks_owned: "你持有的开放风险",
    projects_active: "活跃项目数",
  },
  signOut: "退出",
  onboardingHeading: "入职导览",
  onboardingBody: "下次进入该项目时再次打开第一天导览。",
  onboardingReplayButton: "在该项目重放",
  onboardingNoProjects: "尚未加入任何项目。",
};

export function profileMessages(locale: Locale): ProfileMessages {
  return locale === "zh" ? ZH : EN;
}

export function pickLocale(acceptLanguage: string | null | undefined): Locale {
  if (!acceptLanguage) return "en";
  // Light parser — we only distinguish zh-* from everything else.
  const first = acceptLanguage.split(",")[0]?.trim().toLowerCase() ?? "";
  return first.startsWith("zh") ? "zh" : "en";
}
