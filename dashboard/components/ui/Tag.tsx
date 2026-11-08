import { cn } from "@/lib/cn";

/** Small neutral tag (job type, resume used, skill chips). 12 px, radius 6. */
export function Tag({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-block rounded-control bg-jp-muted-bg px-2 py-0.5 text-xs text-jp-ink-2", className)}>
      {children}
    </span>
  );
}
