"use client";

import { useEffect, useState } from "react";
import { useEngine } from "@/components/shell/EngineProvider";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusLine } from "@/components/ui/StatusLine";
import { TextArea } from "@/components/ui/TextArea";
import { ApiError, getFillJob, getJobPost, startFill } from "@/lib/api";
import type { FillIn, FillJob, JobPostPreview } from "@/lib/api-types";
import { shortUrl } from "@/lib/format";
import { FillSummary } from "./FillSummary";
import { NeedsYou } from "./NeedsYou";
import { TabPicker } from "./TabPicker";

/** Where the job post comes from for the next fill. `auto` = the engine's finder decides. */
type Choice =
  | { kind: "auto" }
  | { kind: "tab"; url: string; title: string }
  | { kind: "paste"; text: string }
  | { kind: "none" };

type Preview = { url: string; data: JobPostPreview | null; error: string | null };

const POLL_JOB_MS = 1500;

function bodyOf(choice: Choice): FillIn {
  switch (choice.kind) {
    case "tab":
      return { post_tab_url: choice.url };
    case "paste":
      return { post_text: choice.text };
    case "none":
      return { no_resume: true };
    default:
      return {};
  }
}

/** The engine's job start time ("2026-11-26 17:18:08", the engine computer's local time) as milliseconds. */
function localMs(stamp: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/.exec(stamp);
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() : null;
}

/**
 * Fill this page (SPEC Part 2, section 1; design/screens/Fill.html), the remote control next to the bot's Chrome.
 *
 * 1. The status line names the page open in the bot's browser (GET /status, every 4 s, from EngineProvider).
 * 2. When that page changes, GET /jobpost shows which job post a fill would use, with Change.
 * 3. "Fill this page" sends POST /fill and then asks GET /fill/{id} every 1.5 s until it is done.
 *    A reloaded dashboard picks the running fill up again from /status.
 * It never clicks Submit: the engine only types into fields. You review the page and submit yourself.
 */
export function FillScreen() {
  const { status, error: engineError, refresh } = useEngine();
  const browserOpen = Boolean(status?.browser_open);
  const pageUrl = status?.page_url ?? null;

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<FillJob | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [now, setNow] = useState(0); // set by the 1 s timer and by Fill, never during render (prerender-safe)
  const [preview, setPreview] = useState<Preview | null>(null);
  const [choice, setChoice] = useState<{ forUrl: string | null; value: Choice }>({ forUrl: null, value: { kind: "auto" } });
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickedTab, setPickedTab] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");
  const [filledUrl, setFilledUrl] = useState<string | null>(null);

  // Follow the fill this screen started, or one that was already running when the page loaded.
  const followId = jobId ?? (status?.fill_running ? status.fill_job_id : null);
  const current = job && job.job_id === followId ? job : null;
  const filling = Boolean(followId) && (!current || current.status === "running");
  const done = current?.status === "done" ? current.result : null;
  const jobError = current?.status === "error" ? current.error : null;

  // Your choice of job post belongs to the page it was made on; a new page starts again with the finder.
  const activeChoice: Choice = choice.forUrl === pageUrl ? choice.value : { kind: "auto" };

  useEffect(() => {
    if (!followId) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await getFillJob(followId);
        if (stop) return;
        setJob(j);
        // A fill picked up from /status after a reload: remember it, because /status stops naming it once it ends.
        setJobId((mine) => mine ?? j.job_id);
        if (j.status !== "running") {
          stop = true;
          refresh(); // a fill adds history rows and unknown questions: update the sidebar counts now
        }
      } catch (e) {
        if (!stop && e instanceof ApiError && e.code === "not_found") {
          stop = true;
          setJobId(null); // the engine restarted and forgot the job; its history row is still saved
        }
      }
    };
    void tick();
    const id = setInterval(() => {
      if (!stop) void tick();
    }, POLL_JOB_MS);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [followId, refresh]);

  useEffect(() => {
    if (!filling) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [filling]);

  // Which job post would a fill use? Asked once per page (the engine logs each look as a read).
  useEffect(() => {
    if (!browserOpen || !pageUrl || filling) return;
    let cancelled = false;
    getJobPost()
      .then((data) => !cancelled && setPreview({ url: pageUrl, data, error: null }))
      .catch((e: unknown) => !cancelled && setPreview({ url: pageUrl, data: null, error: e instanceof Error ? e.message : String(e) }));
    return () => {
      cancelled = true;
    };
  }, [browserOpen, pageUrl, filling]);

  const pagePreview = preview && preview.url === pageUrl ? preview : null;
  const notFound = Boolean(pagePreview?.data && !pagePreview.data.post);
  const showPicker = !filling && browserOpen && Boolean(pageUrl) && (pickerOpen || (notFound && activeChoice.kind === "auto" && !done));

  async function fill(next: Choice) {
    setStarting(true);
    setStartError(null);
    setPickerOpen(false);
    setChoice({ forUrl: pageUrl, value: next });
    try {
      const started = await startFill(bodyOf(next));
      setJob(started);
      setJobId(started.job_id);
      setFilledUrl(pageUrl);
      setNow(Date.now());
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
      refresh();
    }
  }

  function fillWithChosenPost() {
    const text = pasted.trim();
    if (text) {
      void fill({ kind: "paste", text });
      return;
    }
    const tab = pagePreview?.data?.tabs.find((t) => t.url === pickedTab);
    if (tab) void fill({ kind: "tab", url: tab.url, title: tab.title });
  }

  /** "Job post: Backend Intern – Globex (opener tab)", from your choice or the finder's preview. */
  function postLine(): { text: string; muted?: boolean } {
    switch (activeChoice.kind) {
      case "tab":
        return { text: `${activeChoice.title || shortUrl(activeChoice.url)} (tab you picked)` };
      case "paste":
        return { text: "Text you pasted" };
      case "none":
        return { text: "None · no resume uploaded", muted: true };
    }
    if (done?.post) return { text: done.post.label };
    if (!pagePreview) return { text: "Looking for the job post…", muted: true };
    if (pagePreview.error) return { text: "Found when you press Fill", muted: true };
    if (pagePreview.data?.post) return { text: pagePreview.data.post.label };
    return { text: "Not found", muted: true };
  }

  const startedMs = current ? localMs(current.started_at) : null;
  const elapsed = now && startedMs ? Math.max(0, Math.round((now - startedMs) / 1000)) : 0;
  const canFill = browserOpen && Boolean(pageUrl) && !filling && !starting && !engineError;
  const line = postLine();
  const banner = startError ?? jobError;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Fill this page" subtitle="Open an application form in the bot's Chrome, then press Fill. JobPilot never clicks Submit." />

      {status && !browserOpen && (
        <Banner
          tone="danger"
          message="The bot's Chrome is closed. Start it with: python -m engine.cli browser open, open the application page, then come back here."
          actionLabel="Check again"
          onAction={refresh}
        />
      )}
      {banner && <Banner tone="danger" message={banner} actionLabel="Got it" onAction={() => { setStartError(null); setJobId(null); setJob(null); }} />}

      <div className="grid grid-cols-[3fr_2fr] items-start gap-4">
        <div className="flex flex-col gap-3.5 rounded-card border border-jp-line bg-jp-surface px-[22px] py-5">
          {filling ? (
            <StatusLine spinning>
              Filling {shortUrl(filledUrl ?? pageUrl)} · {elapsed} s
            </StatusLine>
          ) : !status ? (
            <StatusLine tone="idle">Connecting to the engine…</StatusLine>
          ) : !browserOpen ? (
            <StatusLine tone="idle">Browser not found</StatusLine>
          ) : pageUrl ? (
            <StatusLine>
              Browser ready · current page: <b className="font-medium text-jp-ink">{shortUrl(pageUrl, 60)}</b>
            </StatusLine>
          ) : (
            <StatusLine tone="idle">Browser open · no web page is open yet</StatusLine>
          )}

          {showPicker ? (
            <>
              {notFound && activeChoice.kind === "auto" ? (
                <div className="rounded-card border border-jp-amber-border bg-jp-amber-bg px-4 py-3 text-sm text-jp-amber-text">
                  <b className="font-semibold">Job post not found.</b> I can&apos;t pick a resume without it, so none will be uploaded until you
                  choose one.
                </div>
              ) : (
                <span className="text-sm font-semibold">Choose the job post for this page</span>
              )}
              <div className="flex flex-col gap-2">
                <span className="text-label font-medium text-jp-ink-2">Pick the tab with the job post</span>
                <TabPicker tabs={pagePreview?.data?.tabs ?? []} picked={pickedTab} onPick={(url) => { setPickedTab(url); setPasted(""); }} />
              </div>
              <TextArea label="Or paste the job post text" value={pasted} onChange={setPasted} rows={3} dashed placeholder="Paste here…" />
              <Button variant="primary" className="h-11 w-full text-[15px]" disabled={!canFill || (!pasted.trim() && !pickedTab)} onClick={fillWithChosenPost}>
                Use this job post and fill
              </Button>
              <Button className="w-full" disabled={!canFill} onClick={() => void fill({ kind: "none" })}>
                Fill without resume
              </Button>
              {pickerOpen && (
                <Button variant="link" className="self-start" onClick={() => setPickerOpen(false)}>
                  Cancel
                </Button>
              )}
            </>
          ) : (
            <>
              {done ? (
                <FillSummary result={done} />
              ) : (
                <span className="border-t border-jp-line-soft" />
              )}
              {done && done.messages.length > 0 && (
                <ul className="flex flex-col gap-1 text-label text-jp-ink-2">
                  {done.messages.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              )}
              {done && <span className="border-t border-jp-line-soft" />}
              <div className="flex items-center justify-between gap-3">
                <div className="flex flex-col gap-1">
                  <span className="text-label font-medium text-jp-ink-2">{done ? "Job post used" : "Job post"}</span>
                  <span className={line.muted ? "text-sm text-jp-ink-2" : "text-sm"}>{line.text}</span>
                </div>
                {!filling && browserOpen && pageUrl && (
                  <Button variant="link" onClick={() => setPickerOpen(true)}>
                    Change
                  </Button>
                )}
              </div>
              {done && (
                <div className="flex flex-col gap-1">
                  <span className="text-label font-medium text-jp-ink-2">Resume</span>
                  <span className="text-sm">
                    {done.resume_id
                      ? `Resume ${done.resume_id}${done.resume_reason ? ` · ${done.resume_reason}` : ""}`
                      : "None uploaded. Upload one by hand if the form needs it."}
                  </span>
                </div>
              )}
              {done ? (
                <>
                  <div className="flex items-center gap-2 pt-1">
                    {done.unknown_ids.length > 0 ? (
                      <Button variant="primary" href={`/questions?id=${done.unknown_ids[0]}`}>
                        {done.unknown_ids.length === 1 ? "Answer the new question" : `Answer the ${done.unknown_ids.length} new questions`}
                      </Button>
                    ) : (
                      <Button variant="primary" href="/history">
                        Open Filled pages
                      </Button>
                    )}
                    <Button disabled={!canFill} onClick={() => void fill(activeChoice)}>
                      Fill this page again
                    </Button>
                  </div>
                  <p className="text-label text-jp-ink-2">After you submit in the browser, mark it in Filled pages.</p>
                </>
              ) : (
                <>
                  <Button variant="primary" className="h-11 w-full text-[15px]" disabled={!canFill} onClick={() => void fill(activeChoice)}>
                    {filling || starting ? "Filling…" : "Fill this page"}
                  </Button>
                  <p className="text-label leading-normal text-jp-ink-2">
                    {filling
                      ? "Reading the form, answering, choosing a resume and filling. The first fill of the day takes longer (the local AI model loads, about 20–50 s). Don't type in the form until it is done."
                      : "Nothing is submitted. You review the form in the browser and click Submit yourself."}
                  </p>
                </>
              )}
            </>
          )}
        </div>
        <NeedsYou />
      </div>
    </div>
  );
}
