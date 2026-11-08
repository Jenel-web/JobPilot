"use client";

import { cn } from "@/lib/cn";

export type Column<T> = {
  key: string;
  header: string;
  /** CSS grid track for this column, e.g. "64px" or "1.4fr". */
  width: string;
  render: (row: T) => React.ReactNode;
};

/**
 * Sticky header (12 px / 600, ink-2), 36 px rows, soft dividers, row hover.
 * A row click calls `onRowClick`, which the screen uses to open a Drawer.
 * Matches design/screens/Applications.html.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectedKey?: string | null;
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
          <span key={c.key} role="columnheader">
            {c.header}
          </span>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
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
                "tabular grid h-[var(--jp-row)] items-center gap-2.5 border-b border-jp-line-soft px-3.5 text-label",
                onRowClick && "cursor-pointer hover:bg-jp-ground",
                selected && "border-l-[3px] border-l-jp-brand bg-jp-brand-tint hover:bg-jp-brand-tint",
              )}
              style={{ gridTemplateColumns: template }}
            >
              {columns.map((c) => (
                <span key={c.key} role="cell" className="min-w-0 truncate">
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
