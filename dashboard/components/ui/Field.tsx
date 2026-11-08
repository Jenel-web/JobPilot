"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

const inputClass =
  "h-10 w-full rounded-control border border-jp-line-strong bg-jp-surface px-3 text-sm text-jp-ink focus-visible:outline-2 focus-visible:outline-jp-brand";

/**
 * A labelled text input. With `sensitive`, the value is masked until the user
 * presses "Show", and an "Encrypted · never sent to AI" tag appears
 * (Profile screen, design/screens/Profile.html).
 */
export function Field({
  label,
  value,
  onChange,
  sensitive,
  mask,
  tag = "Encrypted · never sent to AI",
  className,
}: {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  /** Mask the value until "Show" is pressed. */
  sensitive?: boolean;
  /** What to show while masked, e.g. "●●●● ●●●● 1234". */
  mask?: string;
  tag?: string;
  className?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  const masked = sensitive && !revealed;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-center justify-between text-label text-jp-ink-2">
        <label>{label}</label>
        {sensitive && (
          <button type="button" onClick={() => setRevealed((r) => !r)} className="text-jp-ink-2 hover:text-jp-ink">
            {revealed ? "Hide" : "Show"}
          </button>
        )}
      </div>
      <div className="relative">
        <input
          aria-label={label}
          value={masked ? (mask ?? "●●●●●●●●●●●●") : value}
          readOnly={masked}
          onChange={(e) => onChange?.(e.target.value)}
          className={cn(inputClass, sensitive && "pr-[190px]")}
        />
        {sensitive && (
          <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded-control bg-jp-muted-bg px-2 py-0.5 text-xs text-jp-ink-2">
            {tag}
          </span>
        )}
      </div>
    </div>
  );
}
