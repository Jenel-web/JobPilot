"use client";

import { usePathname } from "next/navigation";
import { NavItem } from "@/components/ui/NavItem";
import { shell } from "@/lib/mock-data";

type Item = { href: string; label: string; count?: number; countTone?: "blue" | "amber" };

const ITEMS: Item[] = [
  { href: "/home", label: "Home" },
  { href: "/review", label: "Review batch", count: shell.reviewCount, countTone: "blue" },
  { href: "/applications", label: "Applications" },
  { href: "/questions", label: "Questions", count: shell.questionCount, countTone: "amber" },
  { href: "/emails", label: "Emails" },
  { href: "/profile", label: "Profile" },
  { href: "/settings", label: "Settings" },
  { href: "/activity", label: "Activity log" },
];

/** Home is active only on "/"; every other item is active for its own section. */
function isActive(pathname: string, href: string): boolean {
  return href === "/home" ? pathname === "/home" : pathname === href || pathname.startsWith(`${href}/`);
}

/** Left navigation: 220 px wide, 8 items, counts on Review batch and Questions. */
export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="flex w-[var(--jp-sidebar)] shrink-0 flex-col gap-0.5 border-r border-jp-line bg-jp-surface px-2.5 py-4 text-sm"
    >
      {ITEMS.map((item) => (
        <NavItem key={item.href} {...item} active={isActive(pathname, item.href)} />
      ))}
      <span className="flex-1" />
      <div className="px-2.5 text-label leading-[1.6] text-jp-ink-2">
        {shell.todayLabel}
        <br />
        {shell.activeHours}
        <br />
        {shell.version}
      </div>
    </nav>
  );
}
