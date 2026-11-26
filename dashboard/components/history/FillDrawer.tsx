"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { Tag } from "@/components/ui/Tag";
import { TriangleIcon } from "@/components/ui/icons";
import { screenshotUrl } from "@/lib/api";
import type { FilledPage } from "@/lib/api-types";
import { dateLabel, isWebUrl, shortUrl } from "@/lib/format";
import { FillStatusChip } from "./FillStatusChip";

export function fillTitle(f: FilledPage): string {
  if (!f.job_title) return f.company ? `Form at ${f.company}` : "Form without a job post";
  return f.company ? `${f.job_title} – ${f.company}` : f.job_title;
}

/** The screenshot taken right after the fill, or a plain line when there is none (or the file is gone). */
function Screenshot({ fill }: { fill: FilledPage }) {
  const [broken, setBroken] = useState(false);
  if (!fill.screenshot_path || broken) {
    return <span className="text-label text-jp-ink-2">{fill.screenshot_path ? "The screenshot file is missing." : "No screenshot was taken."}</span>;
  }
  const src = screenshotUrl(fill.id);
  return (
    <div className="relative overflow-hidden rounded-control border border-jp-line bg-jp-ground">
      {/* eslint-disable-next-line @next/next/no-img-element -- a local PNG from the engine on 127.0.0.1; nothing to optimise */}
      <img src={src} alt={`Screenshot of ${fillTitle(fill)} after filling`} className="block max-h-[260px] w-full object-cover object-top" onError={() => setBroken(true)} />
      <Button href={src} external size="sm" className="absolute bottom-2.5 right-2.5">
        Open full size
      </Button>
    </div>
  );
}

/**
 * One filled page (design/screens/History.html, frame 2): screenshot, then what was flagged and what was filled,
 * BY LABEL ONLY. The engine never sends typed values (they could be your phone or email); the screenshot is where
 * you see them. A page still "filled" can be marked once: submitted or abandoned.
 */
export function FillDrawer({
  fill,
  busy,
  onClose,
  onSubmitted,
  onAbandon,
}: {
  fill: FilledPage;
  busy: boolean;
  onClose: () => void;
  onSubmitted: (f: FilledPage) => void;
  onAbandon: (f: FilledPage) => void;
}) {
  return (
    <Drawer
      open
      onClose={onClose}
      label="Filled page details"
      header={
        <>
          <h2 className="text-[20px] font-semibold leading-snug">{fillTitle(fill)}</h2>
          <span>
            <FillStatusChip status={fill.status} />
          </span>
        </>
      }
    >
      <div className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-2 text-sm">
        <span className="text-label font-medium text-jp-ink-2">Page</span>
        {isWebUrl(fill.url) ? (
          <a href={fill.url} target="_blank" rel="noreferrer" className="break-all font-medium text-jp-brand">
            {shortUrl(fill.url, 60)}
          </a>
        ) : (
          <span className="break-all">{shortUrl(fill.url, 60)}</span>
        )}
        <span className="text-label font-medium text-jp-ink-2">Filled</span>
        <span>{dateLabel(fill.filled_at)}</span>
        <span className="text-label font-medium text-jp-ink-2">Resume</span>
        <span>{fill.resume_id ?? "None uploaded"}</span>
        {fill.submitted_at && (
          <>
            <span className="text-label font-medium text-jp-ink-2">Submitted</span>
            <span>{dateLabel(fill.submitted_at)}</span>
          </>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-label font-medium text-jp-ink-2">Screenshot after filling</span>
        <Screenshot fill={fill} />
      </div>

      {fill.flagged_fields.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-label font-medium text-jp-ink-2">Flagged · {fill.flagged_fields.length}</span>
          {fill.flagged_fields.map((f, i) => (
            <div key={`${f.label}-${i}`} className="flex items-start gap-2.5 text-sm leading-snug">
              <TriangleIcon className="mt-0.5 shrink-0 text-jp-amber" />
              <span>
                <b className="font-semibold">{f.label || "(no label)"}</b>
                <br />
                <span className="text-label text-jp-ink-2">{f.note || f.outcome}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-label font-medium text-jp-ink-2">Filled · {fill.filled_fields.length}</span>
        <div className="flex flex-wrap gap-1.5">
          {fill.filled_fields.map((label, i) => (
            <Tag key={`${label}-${i}`}>{label}</Tag>
          ))}
        </div>
        <span className="text-label text-jp-ink-2">Field names only. The typed values are in the screenshot, never sent to the dashboard.</span>
      </div>

      <div className="mt-auto flex items-center gap-2 border-t border-jp-line-soft pt-4">
        {fill.status === "filled" ? (
          <>
            <Button disabled={busy} onClick={() => onAbandon(fill)}>
              Abandoned
            </Button>
            <span className="flex-1" />
            <Button variant="primary" disabled={busy} onClick={() => onSubmitted(fill)}>
              Mark as submitted
            </Button>
          </>
        ) : (
          <span className="text-label text-jp-ink-2">Status is final: a page can be marked once.</span>
        )}
      </div>
    </Drawer>
  );
}
