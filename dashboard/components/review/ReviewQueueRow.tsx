import { Checkbox } from "@/components/ui/Checkbox";
import { TriangleIcon } from "@/components/ui/icons";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { StatusChip } from "@/components/ui/StatusChip";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { resumeNames, type ReviewItem } from "@/lib/mock/review";
import type { Decision } from "./types";

const CHIP: Record<Decision, { status: "queued" | "approved" | "rejected" | "submitted"; label?: string }> = {
  queued: { status: "queued" },
  approved: { status: "approved", label: "Approved ✓" },
  rejected: { status: "rejected" },
  submitting: { status: "approved", label: "Submitting…" },
  submitted: { status: "submitted" },
};

/** One compact card in the Review queue (design/screens/Review.html). */
export function ReviewQueueRow({
  item,
  decision,
  flags,
  resumeId,
  selected,
  checked,
  onSelect,
  onCheck,
}: {
  item: ReviewItem;
  decision: Decision;
  flags: number;
  resumeId: "A" | "B";
  selected: boolean;
  checked: boolean;
  onSelect: () => void;
  onCheck: (checked: boolean) => void;
}) {
  const chip = CHIP[decision];
  return (
    <div
      role="option"
      aria-selected={selected}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect();
      }}
      className={cn(
        "grid cursor-pointer grid-cols-[auto_40px_1fr_auto] items-center gap-2.5 border-b border-jp-line-soft px-3.5 py-2.5",
        selected ? "border-l-[3px] border-l-jp-brand bg-jp-brand-tint" : "hover:bg-jp-ground",
        decision === "rejected" && "opacity-60",
      )}
    >
      <Checkbox checked={checked} onChange={onCheck} ariaLabel={`Select ${item.title} at ${item.company}`} />
      <ScoreBadge score={item.score} size={36} />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-sm font-semibold">{item.title}</span>
        <span className="text-label text-jp-ink-2">
          {item.company} · {item.location}
        </span>
        <span className="mt-[3px] flex flex-wrap items-center gap-1.5">
          <Tag>{item.type}</Tag>
          <Tag>
            Resume {resumeId} · {resumeNames[resumeId]}
          </Tag>
          {flags > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-jp-amber-text">
              <TriangleIcon size={11} className="text-jp-amber" />
              {flags} {flags === 1 ? "answer" : "answers"} guessed by AI
            </span>
          )}
        </span>
      </span>
      <StatusChip status={chip.status} label={chip.label} size="sm" />
    </div>
  );
}
