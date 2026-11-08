import type { DayBar } from "@/lib/mock/home";

const WIDTH = 600;
const HEIGHT = 170;
const BASELINE = 150;
const SIDE = 10; // empty space left and right of the bars

/**
 * Bar chart of applications per day, drawn as plain SVG (no chart library).
 * Green bars were submitted by JobPilot, purple bars need a manual apply.
 */
export function ApplicationsChart({ days }: { days: DayBar[] }) {
  // Spread the bars across the full width, whatever the number of days.
  const step = (WIDTH - SIDE * 2) / Math.max(1, days.length);
  const barWidth = step * 0.67;
  return (
    <div className="flex flex-col gap-3 rounded-card border border-jp-line bg-jp-surface px-[18px] py-4">
      <span className="text-sm font-semibold">Applications per day, last 30 days</span>
      <svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Bar chart of applications per day, split submitted and manual"
        className="block"
      >
        <line x1="0" y1={BASELINE} x2={WIDTH} y2={BASELINE} className="stroke-jp-line" />
        {days.map((d, i) => (
          <rect
            key={i}
            x={SIDE + i * step}
            y={BASELINE - d.count}
            width={barWidth}
            height={d.count}
            className={d.kind === "submitted" ? "fill-jp-status-submitted" : "fill-jp-status-manual"}
          />
        ))}
      </svg>
      <div className="flex gap-4 text-label text-jp-ink-2">
        <span>
          <span className="mr-1 inline-block size-2.5 rounded-sm bg-jp-status-submitted align-middle" /> Submitted
        </span>
        <span>
          <span className="mr-1 inline-block size-2.5 rounded-sm bg-jp-status-manual align-middle" /> Manual
        </span>
      </div>
    </div>
  );
}
