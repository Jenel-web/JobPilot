import { cn } from "@/lib/cn";

/** A native dropdown styled like the 32 px bordered controls in the mockups. */
export function Select({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  /** Accessible name, e.g. "Status". Also shown as the first option's context. */
  label: string;
  className?: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "h-8 rounded-control border border-jp-line-strong bg-jp-surface px-2.5 text-label text-jp-ink",
        "focus-visible:outline-2 focus-visible:outline-jp-brand",
        className,
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
