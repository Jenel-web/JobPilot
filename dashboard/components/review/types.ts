import type { ResumeId } from "@/lib/types";

/** Where a job is in the review flow. "submitting" is the spinner state after "Submit approved". */
export type Decision = "queued" | "approved" | "rejected" | "submitting" | "submitted";

/** Everything the user can edit for one job before approving it. */
export type Draft = {
  resume: ResumeId;
  /** Edited answers, keyed by question text. */
  answers: Record<string, string>;
  saveToBank: boolean;
  emailSubject: string;
  emailBody: string;
  skipEmail: boolean;
  /** Pasted address when no verified contact was found. */
  manualEmail: string;
};

export const REJECT_REASONS = [
  "Not interested",
  "Bad match",
  "Wrong location",
  "Already applied elsewhere",
  "Block this company",
] as const;
export type RejectReason = (typeof REJECT_REASONS)[number];
