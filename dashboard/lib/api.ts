/**
 * The ONLY place the dashboard talks to the engine API (engine/api.py, 127.0.0.1 only).
 *
 * The dashboard never opens the database or answers.json itself: every read and change goes through the
 * engine, which makes the backup, checks protected answers and re-indexes. These functions run in the
 * browser (client components), so the engine sees the dashboard's Origin (localhost:3000), which its guard
 * allows. Set NEXT_PUBLIC_ENGINE_URL to use another port (the sandbox in scripts/api_sandbox.py uses 8001).
 */

import type {
  AnswerChangeOut,
  AnswerDeleteOut,
  AnswerIn,
  AnswerUpdateIn,
  DecisionOut,
  EngineStatus,
  FilledPage,
  FillIn,
  FillJob,
  FillStatus,
  JobPostPreview,
  SavedAnswer,
  UnknownAnswerIn,
  UnknownAnswerOut,
  UnknownQuestion,
  Wording,
} from "./api-types";

export const ENGINE_URL = (process.env.NEXT_PUBLIC_ENGINE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

/** Codes the screens react to. Anything else is shown as the engine's own message. */
export type ErrorCode =
  | "engine_unreachable"
  | "not_found"
  | "protected_needs_confirmation"
  | "already_decided"
  | "already_exists"
  | "not_allowed"
  | "invalid"
  | "fill_running"
  | "index_not_ready"
  | "browser_closed"
  | "ai_unavailable"
  | "no_page"
  | "unknown";

/**
 * An engine error in plain words. `message` is what a Banner shows; `code` is for the screen's logic
 * (for example, "protected_needs_confirmation" opens the ConfirmDialog instead of showing an error).
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const ENGINE_DOWN_MESSAGE = "The engine isn't running. Start it with: python -m engine.api";

/** FastAPI's own 422 body is a list of problems; the engine's errors are {code, detail}. Both become one sentence. */
function messageOf(body: unknown, status: number): { code: ErrorCode; message: string } {
  if (body && typeof body === "object" && "detail" in body) {
    const { detail, code } = body as { detail: unknown; code?: string };
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined;
      return { code: "invalid", message: first?.msg?.replace(/^Value error, /, "") ?? "The request was not valid." };
    }
    if (typeof detail === "string") return { code: (code as ErrorCode) ?? "unknown", message: detail };
  }
  return { code: "unknown", message: `The engine answered with an error (${status}).` };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${ENGINE_URL}${path}`, {
      ...init,
      headers: init.body ? { "Content-Type": "application/json", ...init.headers } : init.headers,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "engine_unreachable", ENGINE_DOWN_MESSAGE);
  }
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // not JSON: keep the generic message
    }
    const { code, message } = messageOf(body, response.status);
    throw new ApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

// ---- reads ----------------------------------------------------------------

export const getStatus = () => request<EngineStatus>("/status");
export const getUnknown = () => request<UnknownQuestion[]>("/unknown");
export const getWordings = () => request<Wording[]>("/wordings");
export const getAnswers = () => request<SavedAnswer[]>("/answers");
export const getFills = (status?: FillStatus) =>
  request<FilledPage[]>(status ? `/fills?status=${status}&limit=500` : "/fills?limit=500");
export const getJobPost = () => request<JobPostPreview>("/jobpost");
export const getFillJob = (jobId: string) => request<FillJob>(`/fill/${encodeURIComponent(jobId)}`);

/** Address of a fill's screenshot (an <img src>); the engine only sends PNGs from data/screenshots/. */
export const screenshotUrl = (fillId: number) => `${ENGINE_URL}/fills/${fillId}/screenshot`;

// ---- changes (each one makes a backup and re-indexes inside the engine) ----

export const answerUnknown = (id: number, body: UnknownAnswerIn) =>
  post<UnknownAnswerOut>(`/unknown/${id}/answer`, body);
export const approveWording = (id: number, confirmProtected: boolean) =>
  post<DecisionOut>(`/wordings/${id}/approve`, { confirm_protected: confirmProtected });
export const rejectWording = (id: number) => post<DecisionOut>(`/wordings/${id}/reject`);
export const addAnswer = (body: AnswerIn) => post<AnswerChangeOut>("/answers", body);
export const updateAnswer = (id: number, body: AnswerUpdateIn) =>
  request<AnswerChangeOut>(`/answers/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteAnswer = (id: number, confirmProtected: boolean) =>
  request<AnswerDeleteOut>(`/answers/${id}?confirm_protected=${confirmProtected}`, { method: "DELETE" });
export const markFill = (id: number, status: "submitted" | "abandoned") =>
  post<FilledPage>(`/fills/${id}/status`, { status });

// ---- the fill job: start it, then ask how it is going -----------------------

export const startFill = (body: FillIn = {}) => post<FillJob>("/fill", body);
