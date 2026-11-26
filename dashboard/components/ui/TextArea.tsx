import { cn } from "@/lib/cn";

/** A labelled multi-line text box (answers, pasted job posts). Same border and focus ring as Field. */
export function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 4,
  dashed = false,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  /** Dashed border on a ground background: a box you paste into (design/screens/Fill.html). */
  dashed?: boolean;
  className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1.5", className)}>
      <span className="text-label font-medium text-jp-ink-2">{label}</span>
      <textarea
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-full resize-y rounded-control border border-jp-line-strong px-3 py-2.5 text-sm leading-normal text-jp-ink",
          "focus-visible:outline-2 focus-visible:outline-jp-brand",
          dashed ? "border-dashed bg-jp-ground" : "bg-jp-surface",
        )}
      />
    </label>
  );
}
