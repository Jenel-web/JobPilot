import { cn } from "@/lib/cn";
import { Button } from "./Button";

/**
 * Amber (warning) or danger (stopped) banner: a message and exactly one fix
 * button. It stays until the problem is fixed (DESIGN.md).
 */
export function Banner({
  tone,
  message,
  actionLabel,
  onAction,
  actionHref,
}: {
  tone: "amber" | "danger";
  message: string;
  actionLabel: string;
  onAction?: () => void;
  actionHref?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-center justify-between gap-3 rounded-card border px-4 py-3 text-sm text-jp-ink",
        tone === "amber" ? "border-jp-amber-border bg-jp-amber-bg" : "border-jp-danger-border bg-jp-danger-bg",
      )}
    >
      <span>{message}</span>
      {actionHref ? (
        <Button
          href={actionHref}
          size="xs"
          variant="secondary"
          className={tone === "amber" ? "border-jp-amber text-jp-amber-text" : undefined}
        >
          {actionLabel}
        </Button>
      ) : (
        <Button
          size="xs"
          variant={tone === "danger" ? "danger" : "secondary"}
          onClick={onAction}
          className={tone === "amber" ? "border-jp-amber text-jp-amber-text" : undefined}
        >
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
