import { cn } from "@/lib/cn";

/** A small checkbox (14 px) with an optional text label. Colour comes from the brand token. */
export function Checkbox({
  checked,
  onChange,
  label,
  ariaLabel,
  className,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  /** Needed when there is no visible `label`. */
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-label text-jp-ink-2", className)}>
      <input
        type="checkbox"
        checked={checked}
        aria-label={ariaLabel}
        onChange={(e) => onChange(e.target.checked)}
        onClick={(e) => e.stopPropagation()}
        className="size-3.5 cursor-pointer accent-jp-brand"
      />
      {label}
    </label>
  );
}
