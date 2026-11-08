/** Shared types for the mock screens. Statuses match SPEC.md (applications.status). */

export type Status =
  | "new"
  | "queued"
  | "approved"
  | "submitted"
  | "manual"
  | "failed"
  | "rejected"
  | "interview"
  | "offer";

export type RunMode = "mock" | "dry_run" | "live";

export type JobType = "Internship" | "Part-time" | "Freelance" | "Full-time";

export type ResumeId = "A" | "B";
