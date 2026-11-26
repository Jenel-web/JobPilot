"use client";

import { AlertRow } from "@/components/ui/AlertRow";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { StatusChip } from "@/components/ui/StatusChip";
import type { SavedAnswer } from "@/lib/api-types";
import { dateLabel } from "@/lib/format";
import { scopeLabel } from "@/lib/labels";

const RECENT = 15;

/**
 * Answered: the saved answers most recently used by a fill, read only. Editing lives in the Answer bank,
 * so this tab only points there (SPEC 2b: Waiting | Wordings | Answered).
 */
export function AnsweredTab({ answers }: { answers: SavedAnswer[] }) {
  const recent = [...answers]
    .sort((a, b) => (b.last_used ?? "").localeCompare(a.last_used ?? "") || b.times_used - a.times_used)
    .slice(0, RECENT);
  const columns: Column<SavedAnswer>[] = [
    { key: "q", header: "Question", width: "4fr", render: (a) => <b className="font-semibold">{a.question}</b> },
    { key: "a", header: "Answer", width: "4fr", render: (a) => a.answer },
    { key: "kind", header: "Kind", width: "1.2fr", render: (a) => <StatusChip status="new" label={a.kind} /> },
    { key: "scope", header: "Location scope", width: "1.6fr", render: (a) => scopeLabel(a) },
    { key: "used", header: "Last used", width: "1.2fr", render: (a) => (a.last_used ? dateLabel(a.last_used, false) : "Never") },
  ];
  return (
    <div className="flex flex-col gap-3">
      <AlertRow
        tone="blue"
        message={`All ${answers.length} saved answers, with search and editing, are in the Answer bank. Below: the ${Math.min(RECENT, answers.length)} used most recently.`}
        actionLabel="Open Answer bank"
        href="/answers"
      />
      <DataTable columns={columns} rows={recent} rowKey={(a) => String(a.id)} tall emptyMessage="No saved answers yet." />
    </div>
  );
}
