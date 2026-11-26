"use client";

import { useEngine } from "@/components/shell/EngineProvider";
import { AlertRow } from "@/components/ui/AlertRow";
import { plural } from "@/lib/format";

/** "Needs you": short links to the other screens, from the shared sidebar counts (design/screens/Fill.html). */
export function NeedsYou() {
  const { counts } = useEngine();
  const questions = counts ? counts.unknown + counts.wordings : 0;
  const open = counts?.openFills ?? 0;
  return (
    <div className="flex flex-col gap-2.5">
      <span className="text-label font-medium text-jp-ink-2">Needs you</span>
      {questions > 0 && (
        <AlertRow tone="amber" message={`${plural(questions, "question")} to answer or check`} actionLabel="Open Questions" href="/questions" />
      )}
      {open > 0 && (
        <AlertRow tone="blue" message={`${plural(open, "filled page")} without a status`} actionLabel="Open Filled pages" href="/history" />
      )}
      {counts && questions === 0 && open === 0 && <span className="text-label text-jp-ink-2">Nothing waiting.</span>}
    </div>
  );
}
