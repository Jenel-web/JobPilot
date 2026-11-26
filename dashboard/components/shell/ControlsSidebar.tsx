"use client";

import { usePathname } from "next/navigation";
import { NavItem } from "@/components/ui/NavItem";
import { useEngine } from "./EngineProvider";

/** "Fill this page" is active only on "/"; every other item is active for its own section. */
function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * v0 sidebar: the four sections of the controls page (SPEC Part 2, "The v0 controls page").
 * Questions counts unknown questions + wordings to check (amber); Filled pages counts pages you
 * have not marked yet (blue). A zero shows no badge.
 */
export function ControlsSidebar() {
  const pathname = usePathname();
  const { counts } = useEngine();
  const questions = counts ? counts.unknown + counts.wordings : 0;
  const open = counts?.openFills ?? 0;

  return (
    <nav
      aria-label="Main"
      className="flex w-[var(--jp-sidebar)] shrink-0 flex-col gap-0.5 border-r border-jp-line bg-jp-surface px-2.5 py-4 text-sm"
    >
      <NavItem href="/" label="Fill this page" active={isActive(pathname, "/")} />
      <NavItem
        href="/questions"
        label="Questions"
        active={isActive(pathname, "/questions")}
        count={questions || undefined}
        countTone="amber"
      />
      <NavItem href="/answers" label="Answer bank" active={isActive(pathname, "/answers")} />
      <NavItem
        href="/history"
        label="Filled pages"
        active={isActive(pathname, "/history")}
        count={open || undefined}
        countTone="blue"
      />
      <span className="flex-1" />
      <div className="px-2.5 text-label text-jp-ink-2">v0 · form filler</div>
    </nav>
  );
}
