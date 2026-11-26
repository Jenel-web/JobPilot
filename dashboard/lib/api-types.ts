/**
 * The JSON shapes the engine API sends and accepts. A hand copy of engine/api_models.py:
 * when a model there changes, change it here too (the Python file is the source of truth).
 */

import type { RunMode } from "./types";

export type Kind = "fixed" | "open" | "protected";
export type Scope = "any" | "city" | "remote" | "abroad";
export type FillStatus = "filled" | "submitted" | "abandoned";

// ---- reads ----------------------------------------------------------------

export type UnknownQuestion = {
  id: number;
  question: string;
  times_seen: number;
  page_url: string | null; // the page it was last met on
  field_type: string | null;
  options: string[];
  first_seen: string;
  last_seen: string | null;
};

export type Wording = {
  id: number;
  wording: string;
  matched_question: string;
  score: number;
  times_seen: number;
  page_url: string | null;
  protected: boolean; // approving needs the extra confirmation
  kind: Kind;
  first_seen: string;
};

export type SavedAnswer = {
  id: number;
  question: string;
  answer: string;
  kind: Kind;
  location_scope: string;
  city: string;
  times_used: number;
  last_used: string | null;
  also_asked_as: string[];
};

export type FlaggedField = { label: string; outcome: string; note: string };

/** One filled page. Field labels and counts only: the engine never sends typed values. */
export type FilledPage = {
  id: number;
  url: string;
  job_title: string | null;
  company: string | null;
  resume_id: string | null;
  filled_count: number;
  flagged_count: number;
  filled_fields: string[];
  flagged_fields: FlaggedField[];
  screenshot_path: string | null;
  status: FillStatus;
  filled_at: string;
  submitted_at: string | null;
};

export type EngineStatus = {
  run_mode: RunMode;
  browser_open: boolean;
  page_url: string | null;
  page_title: string | null;
  fill_running: boolean;
  fill_job_id: string | null;
};

export type FillPost = { label: string; source: string; tab_title: string; tab_url: string };
export type Tab = { index: number; title: string; url: string };

export type JobPostPreview = { page_url: string; post: FillPost | null; tabs: Tab[] };

export type FillResult = {
  url: string;
  fill_id: number | null;
  filled: number;
  needs_you: number;
  failed: number;
  flagged: number;
  flagged_fields: FlaggedField[];
  screenshot_path: string | null;
  post: FillPost | null;
  tabs: Tab[];
  resume_id: string | null;
  resume_reason: string;
  unknown_ids: number[];
  messages: string[];
};

export type FillJob = {
  job_id: string;
  status: "running" | "done" | "error";
  started_at: string;
  finished_at: string | null;
  result: FillResult | null;
  error: string | null;
};

// ---- what you send --------------------------------------------------------

export type UnknownAnswerIn = { answer: string; kind: Kind; scope: Scope; city: string };
export type AnswerIn = { question: string; answer: string; kind: Kind; scope: Scope; city: string };
export type AnswerUpdateIn = { answer: string; kind: Kind; scope: Scope; city: string; confirm_protected: boolean };
export type FillIn = { tab?: string; post_text?: string; post_tab_url?: string; resume?: "A" | "B"; no_resume?: boolean };

// ---- what comes back after a change ---------------------------------------

/** A failed re-index is a warning, not an error: the change is saved. */
export type ChangeInfo = { backup: string | null; reindexed: boolean; warning: string | null };

export type UnknownAnswerOut = ChangeInfo & { unknown_id: number; answer: SavedAnswer | null };
export type DecisionOut = ChangeInfo & {
  id: number;
  wording: string;
  matched_question: string;
  status: "approved" | "rejected";
};
export type AnswerChangeOut = ChangeInfo & { answer: SavedAnswer };
export type AnswerDeleteOut = ChangeInfo & { deleted_id: number; question: string; removed_wordings: number };
