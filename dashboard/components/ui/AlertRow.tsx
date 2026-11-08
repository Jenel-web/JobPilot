import Link from "next/link";
import { cn } from "@/lib/cn";

/**
 * Home "Needs you" row: a surface card with a 3 px coloured left border,
 * the message on the left and one action link on the right.
 */
export function AlertRow({
  message,
  actionLabel,
  href,
  tone,
}: {
  message: string;
  actionLabel: string;
  href: string;
  tone: "blue" | "amber";
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-card border border-l-[3px] border-jp-line bg-jp-surface px-3.5 py-2.5 text-sm",
        tone === "blue" ? "border-l-jp-status-queued" : "border-l-jp-amber",
      )}
    >
      <span>{message}</span>
      <Link href={href} className="font-semibold text-jp-brand">
        {actionLabel}
      </Link>
    </div>
  );
}
