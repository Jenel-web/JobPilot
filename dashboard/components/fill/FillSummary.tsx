import { Tag } from "@/components/ui/Tag";
import { TriangleIcon } from "@/components/ui/icons";
import type { FillResult } from "@/lib/api-types";
import { plural } from "@/lib/format";

/**
 * The result of one fill (design/screens/Fill.html, frame 3): a tint box with the counts, then the flagged fields
 * BY LABEL with a short reason, so you know what to look at in the page. Values are never shown here.
 */
export function FillSummary({ result }: { result: FillResult }) {
  const newQuestions = result.unknown_ids.length;
  return (
    <>
      <div className="flex flex-col gap-2.5 rounded-card bg-jp-brand-tint px-4 py-3.5">
        <b className="text-[15px] font-semibold text-jp-brand">Done. Review the form in the browser, then submit it yourself.</b>
        <div className="flex flex-wrap gap-1.5">
          <Tag>{result.filled} filled</Tag>
          {newQuestions > 0 && <Tag>{plural(newQuestions, "new question")}</Tag>}
          <Tag>{result.resume_id ? `Resume ${result.resume_id}` : "No resume"}</Tag>
          {result.failed > 0 && <Tag>{result.failed} could not be filled</Tag>}
        </div>
        {result.flagged > 0 && (
          <span className="inline-flex items-center gap-1.5 text-label font-medium text-jp-amber-text">
            <TriangleIcon className="shrink-0 text-jp-amber" />
            {result.flagged} flagged (guessed or needs you). Outlined in amber on the page.
          </span>
        )}
      </div>
      {result.flagged_fields.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-label font-medium text-jp-ink-2">Flagged fields</span>
          <div className="flex flex-col">
            {result.flagged_fields.map((f, i) => (
              <div key={`${f.label}-${i}`} className="flex items-start gap-2.5 border-b border-jp-line-soft py-2.5 text-sm leading-snug last:border-b-0">
                <TriangleIcon className="mt-0.5 shrink-0 text-jp-amber" />
                <span>
                  <b className="font-semibold">{f.label || "(no label)"}</b>
                  <br />
                  <span className="text-label text-jp-ink-2">{f.note || f.outcome}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
