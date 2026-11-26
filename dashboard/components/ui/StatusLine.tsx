import { cn } from "@/lib/cn";

const DOTS = {
  ok: "bg-jp-status-submitted",
  busy: "bg-jp-status-queued",
  idle: "bg-jp-status-new",
  bad: "bg-jp-danger",
} as const;

/**
 * A small coloured dot and one line of 13 px text: "Browser ready · current page: …",
 * "Re-indexing the answer bank…". `spinning` swaps the dot for a turning ring (a fill in progress).
 */
export function StatusLine({
  tone = "ok",
  spinning = false,
  children,
  className,
}: {
  tone?: keyof typeof DOTS;
  spinning?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span role="status" className={cn("inline-flex items-center gap-2 text-label text-jp-ink-2", className)}>
      {spinning ? (
        <span className="size-3.5 shrink-0 animate-spin rounded-full border-2 border-jp-line border-t-jp-brand" />
      ) : (
        <span className={cn("size-2 shrink-0 rounded-full", DOTS[tone])} />
      )}
      <span className="min-w-0">{children}</span>
    </span>
  );
}
