"use client";

import { useState } from "react";

/**
 * Editable list of small chips (keywords, locations, skills, blocklist entries):
 * each has an × to remove it, and a box adds a new one on Enter.
 */
export function ChipList({
  label,
  items,
  onChange,
  placeholder = "Add and press Enter",
}: {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !items.includes(v)) onChange([...items, v]);
    setDraft("");
  };
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      {items.map((item) => (
        <span
          key={item}
          className="inline-flex h-7 items-center gap-1.5 rounded-full bg-jp-muted-bg pl-3 pr-2 text-label text-jp-ink"
        >
          {item}
          <button
            type="button"
            aria-label={`Remove ${item}`}
            onClick={() => onChange(items.filter((i) => i !== item))}
            className="text-jp-ink-2 hover:text-jp-ink"
          >
            ×
          </button>
        </span>
      ))}
      <input
        aria-label={`Add to ${label}`}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        className="h-7 w-[170px] rounded-control border border-jp-line-strong bg-jp-surface px-2.5 text-label placeholder:text-jp-ink-2 focus-visible:outline-2 focus-visible:outline-jp-brand"
      />
    </div>
  );
}
