"use client";

import { Button } from "@/components/ui/Button";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { FlagMarker } from "@/components/ui/FlagMarker";
import { StatusChip } from "@/components/ui/StatusChip";
import type { SavedAnswer, Wording } from "@/lib/api-types";
import { isWebUrl, shortUrl } from "@/lib/format";
import { scopeLabel } from "@/lib/labels";

/**
 * What the matched question is answered with, as the Wordings table shows it. Protected answers are never shown
 * here, only their kind (design/screens/Questions.html, frame 3); open answers are rewritten for each form.
 */
export function savedAnswerText(w: Wording, answers: SavedAnswer[]): string {
  if (w.protected || w.kind === "protected") return "Hidden (protected)";
  if (w.kind === "open") return "(open: written fresh each time)";
  const rows = answers.filter((a) => a.question === w.matched_question);
  if (rows.length === 0) return "";
  if (rows.length === 1) return rows[0].answer;
  return rows.map((a) => `${a.answer} (${scopeLabel(a)})`).join(" · ");
}

/**
 * Wordings: a form asked a saved question in new words. Each row has its own Approve and Reject buttons,
 * most seen first (the engine's order). Scores are plain numbers (no bar: not in the design system).
 */
export function WordingsTab({
  items,
  answers,
  busyId,
  onApprove,
  onReject,
  onShowAnswered,
}: {
  items: Wording[];
  answers: SavedAnswer[];
  busyId: number | null;
  onApprove: (w: Wording) => void;
  onReject: (w: Wording) => void;
  onShowAnswered: () => void;
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        message="No new wordings waiting. When a form words a question in a new way, it appears here."
        actionLabel="See answered questions"
        onAction={onShowAnswered}
      />
    );
  }

  const columns: Column<Wording>[] = [
    {
      key: "wording",
      header: "New wording",
      width: "22fr",
      render: (w) => (
        <span className="flex flex-col gap-0.5">
          <b className="font-semibold">{w.wording}</b>
          {w.page_url &&
            (isWebUrl(w.page_url) ? (
              <a href={w.page_url} target="_blank" rel="noreferrer" className="text-label font-medium text-jp-brand">
                {shortUrl(w.page_url, 36)}
              </a>
            ) : (
              <span className="text-label text-jp-ink-2">{shortUrl(w.page_url, 36)}</span>
            ))}
        </span>
      ),
    },
    { key: "matched", header: "Matches saved question", width: "21fr", render: (w) => w.matched_question },
    {
      key: "answer",
      header: "Saved answer",
      width: "17fr",
      render: (w) => {
        const text = savedAnswerText(w, answers);
        return w.protected || w.kind !== "fixed" ? <span className="text-jp-ink-2">{text}</span> : text;
      },
    },
    { key: "score", header: "Score", width: "7fr", align: "right", render: (w) => w.score.toFixed(2) },
    { key: "seen", header: "Seen", width: "6fr", align: "right", render: (w) => w.times_seen },
    {
      key: "kind",
      header: "Kind",
      width: "12fr",
      render: (w) => (
        <span className="inline-flex items-center gap-2" title={w.protected ? "Matches a protected answer. Check the two questions mean the same thing." : undefined}>
          <StatusChip status="new" label={w.kind} />
          {(w.protected || w.kind === "protected") && <FlagMarker count={1} />}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "15fr",
      render: (w) => (
        <span className="flex justify-end gap-1.5">
          <Button variant="primary" size="sm" disabled={busyId !== null} onClick={() => onApprove(w)}>
            Approve
          </Button>
          <Button size="sm" disabled={busyId !== null} onClick={() => onReject(w)}>
            Reject
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-[600px] text-label leading-normal text-jp-ink-2">
        A form asked a saved question in new words. Nothing is saved until you approve it, because a wrong match would
        become a permanent 1.0 match.
      </p>
      <DataTable columns={columns} rows={items} rowKey={(w) => String(w.id)} tall />
    </div>
  );
}
