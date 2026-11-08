"use client";

import { cn } from "@/lib/cn";

/** On/off toggle with a text label next to it (label text always states the state, e.g. "Auto-send off"). */
export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2.5 text-sm"
    >
      <span
        className={cn(
          "relative inline-block h-[18px] w-9 rounded-full transition-colors",
          checked ? "bg-jp-brand" : "bg-jp-line-strong",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 size-3.5 rounded-full bg-jp-surface transition-all",
            checked ? "left-[21px]" : "left-0.5",
          )}
        />
      </span>
      {label}
    </button>
  );
}
