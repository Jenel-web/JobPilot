"use client";

import { cn } from "@/lib/cn";

export type Column<T> = {
  key: string;
  header: string;
  /** CSS grid track for this column, e.g. "64px" or "1.4fr". */
  width: string;
  render: (row: T) => React.ReactNode;
  /** "right" for numbers (header and cells line up on the right). */
  align?: "left" | "right";
};

/**
 * Sticky header (12 px / 600, ink-2), 36 px rows, soft dividers, row hover.
 * A row click calls `onRowClick`, which the screen uses to open a Drawer.
 * Matches design/screens/Applications.html.
 *
 * `tall` rows (at least 56 px, text wraps instead of being cut) are for rows that hold two lines or
 * 32 px buttons: Questions → Wordings, Answer bank and Filled pages (design/screens/Questions.html).
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  tall = false,
  emptyMessage,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectedKey?: string | null;
  tall?: boolean;
  /** Shown in place of rows when `rows` is empty (screens usually show an EmptyState instead). */
  emptyMessage?: string;
}) {
  const template = columns.map((c) => c.width).join(" ");
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-card border border-jp-line bg-jp-surface">
      <div
        className="sticky top-0 grid h-[var(--jp-row)] shrink-0 items-center gap-2.5 border-b border-jp-line bg-jp-ground px-3.5 text-xs font-semibold text-jp-ink-2"
        style={{ gridTemplateColumns: template }}
        role="row"
      >
        {columns.map((c) => (
          <span key={c.key} role="columnheader" className={c.align === "right" ? "text-right" : undefined}>
            {c.header}
          </span>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 && emptyMessage && <div className="px-3.5 py-6 text-sm text-jp-ink-2">{emptyMessage}</div>}
        {rows.map((row) => {
          const key = rowKey(row);
          const selected = key === selectedKey;
          return (
            <div
              key={key}
              role="row"
              tabIndex={onRowClick ? 0 : undefined}
              onClick={() => onRowClick?.(row)}
              onKeyDown={(e) => {
                if (onRowClick && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  onRowClick(row);
                }
              }}
              className={cn(
                "tabular grid items-center gap-2.5 border-b border-jp-line-soft px-3.5",
                tall ? "min-h-14 py-2 text-sm leading-snug" : "h-[var(--jp-row)] text-label",
                onRowClick && "cursor-pointer hover:bg-jp-ground",
                selected && "border-l-[3px] border-l-jp-brand bg-jp-brand-tint hover:bg-jp-brand-tint",
              )}
              style={{ gridTemplateColumns: template }}
            >
              {columns.map((c) => (
                <span key={c.key} role="cell" className={cn("min-w-0", tall ? "break-words" : "truncate", c.align === "right" && "text-right")}>
                  {c.render(row)}
                </span>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
