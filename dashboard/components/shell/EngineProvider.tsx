"use client";

import { createContext, useCallback, useContext } from "react";
import { getFills, getStatus, getUnknown, getWordings, type ApiError } from "@/lib/api";
import type { EngineStatus } from "@/lib/api-types";
import { usePoll } from "@/lib/usePoll";

export type Counts = { unknown: number; wordings: number; openFills: number };

type EngineState = {
  /** Last answer from GET /status (mode, browser, current page, running fill). Undefined until the first answer. */
  status: EngineStatus | undefined;
  /** Set when the engine did not answer (not running, wrong port). */
  error: ApiError | null;
  /** Sidebar counts: questions waiting (unknown + wordings) and filled pages without a status. */
  counts: Counts | undefined;
  /** Ask for the status and counts again now, e.g. right after answering a question. */
  refresh: () => void;
};

const EngineContext = createContext<EngineState | null>(null);

const STATUS_EVERY_MS = 4000;
const COUNTS_EVERY_MS = 10000;

async function loadCounts(): Promise<Counts> {
  const [unknown, wordings, open] = await Promise.all([getUnknown(), getWordings(), getFills("filled")]);
  return { unknown: unknown.length, wordings: wordings.length, openFills: open.length };
}

/**
 * Keeps the few things every v0 screen shares in one place: the engine's status and the sidebar counts.
 * The top bar, the sidebar, the Fill page and the "Needs you" box all read them from here, so there is
 * one request every few seconds instead of one per component.
 */
export function EngineProvider({ children }: { children: React.ReactNode }) {
  const status = usePoll(getStatus, STATUS_EVERY_MS);
  const counts = usePoll(loadCounts, COUNTS_EVERY_MS);
  const { reload: reloadStatus } = status;
  const { reload: reloadCounts } = counts;
  const refresh = useCallback(() => {
    void reloadStatus();
    void reloadCounts();
  }, [reloadStatus, reloadCounts]);

  return (
    <EngineContext.Provider value={{ status: status.data, error: status.error, counts: counts.data, refresh }}>
      {children}
    </EngineContext.Provider>
  );
}

/** Read the shared engine state. Must be used under <EngineProvider>. */
export function useEngine(): EngineState {
  const ctx = useContext(EngineContext);
  if (!ctx) throw new Error("useEngine must be used inside <EngineProvider>");
  return ctx;
}
