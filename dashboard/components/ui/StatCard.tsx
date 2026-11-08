import { cn } from "@/lib/cn";

/** Surface card: 13 px label, 36 px Newsreader number, 13 px note (green = good, red = bad). */
export function StatCard({
  label,
  value,
  note,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  note?: string;
  tone?: "neutral" | "good" | "bad";
}) {
  return (
    <div className="flex flex-col gap-1.5 rounded-card border border-jp-line bg-jp-surface p-4">
      <span className="text-label text-jp-ink-2">{label}</span>
      <span className="tabular font-serif text-[36px] font-medium leading-none">{value}</span>
      {note && (
        <span
          className={cn(
            "text-label",
            tone === "good" && "text-jp-status-submitted",
            tone === "bad" && "text-jp-danger",
            tone === "neutral" && "text-jp-ink-2",
          )}
        >
          {note}
        </span>
      )}
    </div>
  );
}
