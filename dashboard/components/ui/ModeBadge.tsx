import { cn } from "@/lib/cn";
import type { RunMode } from "@/lib/types";

const MODES: Record<RunMode, { label: string; classes: string }> = {
  mock: { label: "MOCK", classes: "bg-jp-muted-bg text-jp-ink-2" },
  dry_run: { label: "DRY RUN", classes: "bg-jp-status-queued-bg text-jp-status-queued" },
  live: { label: "LIVE", classes: "bg-jp-danger text-white" },
};

/** Shows what the engine is allowed to do. Sits in the top bar on every screen. */
export function ModeBadge({ mode, className }: { mode: RunMode; className?: string }) {
  const m = MODES[mode];
  return (
    <span
      className={cn(
        "inline-flex h-[26px] items-center rounded-control px-3 text-label font-semibold tracking-[0.02em]",
        m.classes,
        className,
      )}
    >
      {m.label}
    </span>
  );
}
