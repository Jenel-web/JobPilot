import { cn } from "@/lib/cn";

/** 28 px pill. Active = ink background + white text; inactive = border + surface. */
export function FilterChip({
  label,
  active = false,
  onClick,
}: {
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex h-7 items-center whitespace-nowrap rounded-full px-3 text-label font-medium",
        active ? "bg-jp-ink text-white" : "border border-jp-line-strong bg-jp-surface text-jp-ink",
      )}
    >
      {label}
    </button>
  );
}
