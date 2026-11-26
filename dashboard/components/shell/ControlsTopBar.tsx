"use client";

import Link from "next/link";
import { ModeBadge } from "@/components/ui/ModeBadge";
import { cn } from "@/lib/cn";
import { useEngine } from "./EngineProvider";

/**
 * v0 top bar (56 px): logo, the run mode the ENGINE reports, and whether the engine answers.
 * No counters, quota or STOP in v0 (CLAUDE.md: no kill switch until later). The mode is shown,
 * never changed here: only you change it, in settings.json. Layout: design/screens/Fill.html.
 */
export function ControlsTopBar() {
  const { status, error } = useEngine();
  const state = error
    ? { dot: "bg-jp-danger", text: "Engine not reachable" }
    : status
      ? { dot: "bg-jp-status-submitted", text: "Engine connected" }
      : { dot: "bg-jp-status-new", text: "Connecting to the engine…" };

  return (
    <header className="relative z-40 flex h-[var(--jp-topbar)] shrink-0 items-center gap-4 border-b border-jp-line bg-jp-surface py-0 pl-5 pr-4">
      <Link href="/" className="font-serif text-[20px] font-medium">
        JobPilot
      </Link>
      {status && <ModeBadge mode={status.run_mode} />}
      <span className="inline-flex items-center gap-2 text-label text-jp-ink-2" role="status">
        <span className={cn("size-2 rounded-full", state.dot)} />
        {state.text}
      </span>
      <span className="flex-1" />
      <span className="text-label text-jp-ink-2">Runs on this computer only</span>
    </header>
  );
}
