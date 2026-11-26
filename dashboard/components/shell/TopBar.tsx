"use client";

import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ModeBadge } from "@/components/ui/ModeBadge";
import { cn } from "@/lib/cn";
import { alerts, shell } from "@/lib/mock-data";
import { useShell } from "./ShellProvider";

/** "Applied 7 / 15" with a thin progress bar under it. */
function Counter({ label, done, cap }: { label: string; done: number; cap: number }) {
  const pct = Math.min(100, Math.round((done / cap) * 100));
  return (
    <span className="tabular inline-flex min-w-[120px] flex-col gap-1 text-label text-jp-ink-2">
      <span>
        {label} {done} / {cap}
      </span>
      <span className="h-[3px] overflow-hidden rounded-sm bg-jp-line-soft">
        <span className="block h-[3px] bg-jp-brand" style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

/**
 * Top bar (56 px, fixed). It answers: what mode am I in, is it running, and
 * does it need me? Combines Patterns.html (counters) and Applications.html
 * (quota, alert count, Pause, STOP) with SPEC.md Part 2.
 */
export function TopBar() {
  const { mode, stopped, paused, stop, togglePause } = useShell();
  const [confirmStop, setConfirmStop] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);

  const status = stopped
    ? { dot: "bg-jp-status-new", text: "Stopped" }
    : paused
      ? { dot: "bg-jp-amber", text: "Paused" }
      : { dot: "bg-jp-status-submitted", text: "Running" };

  return (
    <header
      className={cn(
        "relative z-40 flex h-[var(--jp-topbar)] shrink-0 items-center gap-4 border-b border-jp-line py-0 pl-5 pr-4",
        stopped ? "bg-jp-danger-bg" : "bg-jp-surface",
      )}
    >
      <Link href="/home" className="font-serif text-[20px] font-medium">
        JobPilot
      </Link>
      <Link href="/settings" aria-label="Run mode: open Settings">
        <ModeBadge mode={mode} />
      </Link>
      <span className="inline-flex items-center gap-2 text-label text-jp-ink-2">
        <span className={cn("size-2 rounded-full", status.dot)} />
        {status.text}
      </span>
      <Counter label="Applied" done={shell.applied.done} cap={shell.applied.cap} />
      <Counter label="Emails" done={shell.emails.done} cap={shell.emails.cap} />

      <span className="flex-1" />

      <span className="tabular text-label text-jp-ink-2" title={shell.quota.detail}>
        Quota {shell.quota.left} / {shell.quota.total}
      </span>

      <div className="relative">
        <button
          type="button"
          onClick={() => setAlertsOpen((o) => !o)}
          aria-label={`${alerts.length} alerts`}
          aria-expanded={alertsOpen}
          className="tabular inline-flex h-7 min-w-7 items-center justify-center rounded-full bg-jp-danger px-1.5 text-xs font-semibold text-white"
        >
          {alerts.length}
        </button>
        {alertsOpen && (
          <div className="absolute right-0 top-9 z-50 flex w-[340px] flex-col rounded-card border border-jp-line bg-jp-surface p-1.5 shadow-overlay">
            {alerts.map((a) => (
              <div key={a.id} className="flex items-center justify-between gap-3 rounded-control px-2.5 py-2 text-sm">
                <span>{a.message}</span>
                <Button href={a.href} variant="link" className="h-7 px-2">
                  {a.actionLabel}
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Button size="sm" onClick={togglePause} disabled={stopped}>
        {paused ? "Resume" : "Pause"}
      </Button>
      <Button size="sm" variant="danger" className="px-3.5" onClick={() => setConfirmStop(true)} disabled={stopped}>
        STOP
      </Button>

      <ConfirmDialog
        open={confirmStop}
        title="Stop all browser actions and emails now?"
        confirmLabel="Stop all actions"
        onCancel={() => setConfirmStop(false)}
        onConfirm={() => {
          stop();
          setConfirmStop(false);
        }}
      >
        Browser actions stop before the next step and any email still waiting is held. The job in progress goes back to
        the queue. Nothing runs until you press Resume.
      </ConfirmDialog>
    </header>
  );
}
