"use client";

import type { Tab } from "@/lib/api-types";
import { cn } from "@/lib/cn";
import { shortUrl } from "@/lib/format";

/**
 * "Pick the tab with the job post": your other open tabs as a list of choices (design/screens/Fill.html, frame 4;
 * the same list as the on-page panel in FillPanel.html). One can be chosen; the address is what is sent,
 * because tab numbers shift when a tab opens or closes.
 */
export function TabPicker({ tabs, picked, onPick }: { tabs: Tab[]; picked: string | null; onPick: (url: string) => void }) {
  if (tabs.length === 0) {
    return <span className="text-label text-jp-ink-2">No other tabs are open. Open the job post in a tab, or paste its text below.</span>;
  }
  return (
    <div role="radiogroup" aria-label="Pick the tab with the job post" className="flex flex-col gap-2">
      {tabs.map((t) => {
        const on = t.url === picked;
        return (
          <button
            key={`${t.index}-${t.url}`}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onPick(t.url)}
            className={cn(
              "flex flex-col gap-0.5 rounded-control border px-3 py-2.5 text-left text-sm",
              "focus-visible:outline-2 focus-visible:outline-jp-brand",
              on ? "border-jp-brand bg-jp-brand-tint" : "border-jp-line-strong bg-jp-surface hover:bg-jp-ground",
            )}
          >
            <span>{t.title || "(untitled tab)"}</span>
            <span className="text-label text-jp-ink-2">{shortUrl(t.url, 60)}</span>
          </button>
        );
      })}
    </div>
  );
}
