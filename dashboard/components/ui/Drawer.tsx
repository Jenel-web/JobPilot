"use client";

import { useEffect } from "react";
import { CloseIcon } from "./icons";

/**
 * 520 px panel that slides in from the right, under the top bar, with the
 * overlay shadow and a close X. Escape also closes it.
 * `header` is the title block (Newsreader title, subtitle, chips).
 */
export function Drawer({
  open,
  onClose,
  header,
  children,
  label,
}: {
  open: boolean;
  onClose: () => void;
  header: React.ReactNode;
  children: React.ReactNode;
  /** Accessible name for the panel, e.g. "Application details". */
  label: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <aside
      role="dialog"
      aria-label={label}
      className="fixed bottom-0 right-0 top-[var(--jp-topbar)] z-30 flex w-[var(--jp-drawer)] flex-col overflow-hidden border-l border-jp-line bg-jp-surface shadow-overlay"
    >
      <div className="flex items-start justify-between gap-3 border-b border-jp-line px-[22px] py-[18px]">
        <div className="flex min-w-0 flex-col gap-1.5">{header}</div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-control border border-jp-line-strong text-jp-ink-2"
        >
          <CloseIcon />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-[22px] py-[18px]">{children}</div>
    </aside>
  );
}
