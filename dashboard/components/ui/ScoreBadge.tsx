import { cn } from "@/lib/cn";

const RADIUS = 18;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS; // ~113.1, the full ring

/** Green at 80+, amber 60-79, grey below 60 (DESIGN.md ScoreBadge). */
function tone(score: number): { stroke: string; text: string } {
  if (score >= 80) return { stroke: "stroke-jp-status-submitted", text: "text-jp-status-submitted" };
  if (score >= 60) return { stroke: "stroke-jp-amber", text: "text-jp-amber" };
  return { stroke: "stroke-jp-status-new", text: "text-jp-status-new" };
}

/**
 * A ring that fills to the score, with the number centred inside.
 * `size` is in px: 36 in the Review queue, 40 in other lists, 48 in details.
 */
export function ScoreBadge({ score, size = 40 }: { score: number; size?: 36 | 40 | 48 }) {
  const clamped = Math.max(0, Math.min(100, score));
  const t = tone(clamped);
  const filled = (clamped / 100) * CIRCUMFERENCE;
  return (
    <span
      className="relative inline-block shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Match score ${clamped} out of 100`}
    >
      <svg width={size} height={size} viewBox="0 0 44 44" aria-hidden="true" className="absolute left-0 top-0">
        <circle cx="22" cy="22" r={RADIUS} fill="none" strokeWidth="4" className="stroke-jp-line-soft" />
        <circle
          cx="22"
          cy="22"
          r={RADIUS}
          fill="none"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={`${filled.toFixed(1)} ${CIRCUMFERENCE.toFixed(1)}`}
          transform="rotate(-90 22 22)"
          className={t.stroke}
        />
      </svg>
      <span
        className={cn(
          "tabular absolute inset-0 flex items-center justify-center font-semibold",
          size === 48 ? "text-[15px]" : size === 40 ? "text-label" : "text-xs",
          t.text,
        )}
      >
        {clamped}
      </span>
    </span>
  );
}
