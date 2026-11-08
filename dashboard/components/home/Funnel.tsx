import { cn } from "@/lib/cn";
import type { FunnelStep } from "@/lib/mock/home";

const FILL: Record<FunnelStep["tone"], string> = {
  new: "bg-jp-status-new",
  queued: "bg-jp-status-queued",
  submitted: "bg-jp-status-submitted",
  interview: "bg-jp-status-interview",
};

/**
 * Found → Matched → Submitted → Replied → Interview, as horizontal bars.
 * Each bar is sized against "Found"; the label shows the count and the
 * percentage of the stage before it.
 */
export function Funnel({ steps }: { steps: FunnelStep[] }) {
  const top = steps[0]?.count || 1;
  return (
    <div className="flex flex-col gap-2.5 rounded-card border border-jp-line bg-jp-surface px-[18px] py-4">
      <span className="text-sm font-semibold">Funnel</span>
      <div className="tabular flex flex-col gap-2 text-label">
        {steps.map((step, i) => {
          const prev = i > 0 ? steps[i - 1].count : null;
          const pct = prev ? Math.round((step.count / prev) * 100) : null;
          const width = Math.max(3, Math.round((step.count / top) * 100));
          return (
            <div key={step.label} className="flex items-center gap-2.5">
              <span className="w-[76px] text-jp-ink-2">{step.label}</span>
              <span className="h-[18px] flex-1 rounded bg-jp-line-soft">
                <span className={cn("block h-[18px] rounded", FILL[step.tone])} style={{ width: `${width}%` }} />
              </span>
              <span className="w-16 text-right">
                {step.count}
                {pct !== null && ` · ${pct}%`}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
