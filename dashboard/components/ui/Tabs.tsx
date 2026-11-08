import { cn } from "@/lib/cn";

export type TabItem = { id: string; label: string };

/**
 * Tab buttons. "boxed" (Review batch) = bordered 32 px buttons;
 * "underline" (Applications, Questions, Emails) = text with a brand underline on the active tab.
 */
export function Tabs({
  tabs,
  active,
  onChange,
  variant = "underline",
}: {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  variant?: "boxed" | "underline";
}) {
  return (
    <div role="tablist" className={cn("flex", variant === "boxed" ? "gap-1.5" : "gap-[18px]")}>
      {tabs.map((t) => {
        const on = t.id === active;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.id)}
            className={cn(
              "text-sm",
              variant === "boxed"
                ? cn(
                    "inline-flex h-8 items-center rounded-control border bg-jp-surface px-3",
                    on ? "border-jp-brand font-semibold text-jp-brand" : "border-jp-line text-jp-ink",
                  )
                : cn(
                    "-mb-px border-b-2 py-2",
                    on ? "border-jp-brand font-semibold text-jp-brand" : "border-transparent text-jp-ink-2",
                  ),
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
