"use client";

import { createContext, useCallback, useContext, useState } from "react";
import { shell } from "@/lib/mock-data";
import type { RunMode } from "@/lib/types";

type ShellState = {
  /** Run mode shown in the top bar. Only the person at the dashboard changes it (Settings). */
  mode: RunMode;
  setMode: (mode: RunMode) => void;
  /** Kill switch: true after the user pressed STOP and confirmed. */
  stopped: boolean;
  /** Time the kill switch was pressed, e.g. "3:12 PM". */
  stoppedAt: string | null;
  paused: boolean;
  stop: () => void;
  resume: () => void;
  togglePause: () => void;
};

const ShellContext = createContext<ShellState | null>(null);

function timeLabel(d: Date): string {
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

/**
 * Holds the few things the top bar, the banner and the screens all need to
 * agree on: the run mode, and whether the engine is stopped or paused.
 * (Mock only: real state will live in the engine and be read through the API.)
 */
export function ShellProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<RunMode>(shell.mode);
  const [stopped, setStopped] = useState(false);
  const [stoppedAt, setStoppedAt] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);

  const stop = useCallback(() => {
    setStopped(true);
    setStoppedAt(timeLabel(new Date()));
  }, []);
  const resume = useCallback(() => {
    setStopped(false);
    setStoppedAt(null);
    setPaused(false);
  }, []);
  const togglePause = useCallback(() => setPaused((p) => !p), []);

  return (
    <ShellContext.Provider value={{ mode, setMode, stopped, stoppedAt, paused, stop, resume, togglePause }}>
      {children}
    </ShellContext.Provider>
  );
}

/** Read or change the shell state. Must be used under <ShellProvider>. */
export function useShell(): ShellState {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used inside <ShellProvider>");
  return ctx;
}
