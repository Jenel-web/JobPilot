import { cn } from "@/lib/cn";

/** A 36 px search box that filters a list as you type (Answer bank). Same border and focus ring as Field. */
export function SearchInput({
  label,
  value,
  onChange,
  className,
}: {
  /** Accessible name and placeholder, e.g. "Search questions and answers". */
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <input
      type="search"
      aria-label={label}
      placeholder={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "h-9 w-80 rounded-control border border-jp-line-strong bg-jp-surface px-3 text-sm text-jp-ink",
        "focus-visible:outline-2 focus-visible:outline-jp-brand",
        className,
      )}
    />
  );
}
