import Link from "next/link";
import { cn } from "@/lib/cn";

/**
 * Sidebar link: 36 px, radius 6. Active = brand tint background, brand text, 600.
 * The optional count badge is blue for Review batch and amber for Questions.
 */
export function NavItem({
  href,
  label,
  active,
  count,
  countTone,
}: {
  href: string;
  label: string;
  active: boolean;
  count?: number;
  countTone?: "blue" | "amber";
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-9 items-center justify-between rounded-control px-2.5 text-sm",
        active ? "bg-jp-brand-tint font-semibold text-jp-brand" : "text-jp-ink hover:bg-jp-ground",
      )}
    >
      {label}
      {count !== undefined && (
        <span
          className={cn(
            "tabular inline-flex h-5 min-w-[22px] items-center justify-center rounded-full px-1.5 text-xs font-semibold text-white",
            countTone === "amber" ? "bg-jp-amber" : "bg-jp-status-queued",
          )}
        >
          {count}
        </span>
      )}
    </Link>
  );
}
