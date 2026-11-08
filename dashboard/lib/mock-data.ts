/**
 * MOCK DATA for the dashboard screens. Nothing here comes from the engine:
 * every number and name is sample data (the same samples the design mockups use).
 * When the engine API exists (Phase 4, later), screens swap these imports for
 * fetch calls and this file goes away.
 */

import type { RunMode } from "./types";

// ---- App shell -------------------------------------------------------------

export const shell = {
  mode: "dry_run" as RunMode,
  todayLabel: "Thu, Nov 5",
  activeHours: "Runs 9 AM to 11 PM",
  version: "Version 1.0",
  applied: { done: 7, cap: 15 },
  emails: { done: 4, cap: 10 },
  quota: { left: 38, total: 250, detail: "Gemini 38 left · Ollama local · Hunter 12 left this month" },
  reviewCount: 9,
  questionCount: 3,
};

export type Alert = { id: string; message: string; actionLabel: string; href: string };

export const alerts: Alert[] = [
  { id: "a1", message: "Batch ready (9)", actionLabel: "Review", href: "/review" },
  { id: "a2", message: "3 new questions", actionLabel: "Answer", href: "/questions" },
  { id: "a3", message: "Prosple CAPTCHA", actionLabel: "Open browser", href: "/activity" },
  { id: "a4", message: "Gemini quota used up, switched to Ollama", actionLabel: "Settings", href: "/settings" },
];
