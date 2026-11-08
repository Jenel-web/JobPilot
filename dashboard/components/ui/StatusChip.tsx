import { cn } from "@/lib/cn";
import type { Status } from "@/lib/types";

// Full class names are written out (not built from strings) so Tailwind can see them.
const STYLES: Record<Status, { label: string; classes: string }> = {
  new: { label: "New", classes: "bg-jp-status-new-bg text-jp-status-new" },
  queued: { label: "Queued", classes: "bg-jp-status-queued-bg text-jp-status-queued" },
  approved: { label: "Approved", classes: "bg-jp-status-approved-bg text-jp-status-approved" },
  submitted: { label: "Submitted", classes: "bg-jp-status-submitted-bg text-jp-status-submitted" },
  manual: { label: "Manual", classes: "bg-jp-status-manual-bg text-jp-status-manual" },
  failed: { label: "Failed", classes: "bg-jp-status-failed-bg text-jp-status-failed" },
  rejected: { label: "Rejected", classes: "bg-jp-status-rejected-bg text-jp-status-rejected" },
  interview: { label: "Interview", classes: "bg-jp-status-interview-bg text-jp-status-interview" },
  offer: { label: "Offer", classes: "bg-jp-status-offer-bg text-jp-status-offer" },
};

/** Status label text, so other code can print a status without a chip. */
export function statusLabel(status: Status): string {
  return STYLES[status].label;
}

/**
 * A 24 px pill coloured by status. The text always names the status, so colour
 * is never the only cue (DESIGN.md principle 2).
 */
export function StatusChip({
  status,
  label,
  size = "md",
  className,
}: {
  status: Status;
  label?: string;
  /** "md" = 24 px (lists, headers). "sm" = 22 px (inside table rows, as in Applications.html). */
  size?: "md" | "sm";
  className?: string;
}) {
  const s = STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full font-medium",
        size === "md" ? "h-6 px-2.5 text-label" : "h-[22px] px-[9px] text-xs",
        s.classes,
        className,
      )}
    >
      {label ?? s.label}
    </span>
  );
}
