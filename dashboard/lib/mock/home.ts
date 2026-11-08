/** MOCK DATA for the Home screen. Sample numbers only (same samples as design/screens/Home.html). */

export const greeting = { name: "Jenel", summary: "Found 42 jobs today, 18 matched your filters." };

export type NeedsYou = { id: string; message: string; actionLabel: string; href: string; tone: "blue" | "amber" };

export const needsYou: NeedsYou[] = [
  { id: "review", message: "9 applications ready for review", actionLabel: "Review", href: "/review", tone: "blue" },
  { id: "questions", message: "3 questions need answers", actionLabel: "Answer", href: "/questions", tone: "amber" },
  { id: "captcha", message: "Prosple is paused: CAPTCHA", actionLabel: "Open browser", href: "/activity", tone: "amber" },
];

export const stats = [
  { label: "Found today", value: 42, note: "18 matched (score 60+)", tone: "neutral" as const },
  { label: "Waiting for review", value: 9, note: "oldest 1 day ago", tone: "neutral" as const },
  { label: "Submitted this week", value: 31, note: "+8 vs last week", tone: "good" as const },
  { label: "Emails sent this week", value: 22, note: "2 bounced", tone: "bad" as const },
];

/** One entry per day for the last 30 days: how many applications, and whether they went through or need manual apply. */
export type DayBar = { count: number; kind: "submitted" | "manual" };

const days: Array<[number, DayBar["kind"]]> = [
  [20, "manual"], [38, "submitted"], [50, "submitted"], [26, "submitted"], [32, "submitted"], [60, "submitted"],
  [46, "submitted"], [14, "manual"], [38, "submitted"], [52, "submitted"], [30, "submitted"], [42, "submitted"],
  [66, "submitted"], [48, "submitted"], [24, "manual"], [36, "submitted"], [50, "submitted"], [58, "submitted"],
  [30, "submitted"], [40, "submitted"], [54, "submitted"], [72, "submitted"], [46, "submitted"], [32, "manual"],
  [52, "submitted"], [60, "submitted"], [38, "submitted"], [50, "submitted"], [66, "submitted"], [74, "submitted"],
];
export const applicationsPerDay: DayBar[] = days.map(([count, kind]) => ({ count, kind }));

export type FunnelStep = { label: string; count: number; tone: "new" | "queued" | "submitted" | "interview" };

export const funnel: FunnelStep[] = [
  { label: "Found", count: 142, tone: "new" },
  { label: "Matched", count: 86, tone: "queued" },
  { label: "Submitted", count: 31, tone: "submitted" },
  { label: "Replied", count: 4, tone: "interview" },
  { label: "Interview", count: 1, tone: "interview" },
];

export const recentActivity = [
  { id: "r1", time: "2:14 PM", text: "Submitted · Junior Dev at Acme PH" },
  { id: "r2", time: "1:58 PM", text: "Email sent to Maria Santos" },
  { id: "r3", time: "1:40 PM", text: "Scored 86 · Junior Dev at Acme PH" },
];
