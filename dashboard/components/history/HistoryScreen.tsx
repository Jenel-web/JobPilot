"use client";

import { useState } from "react";
import { useEngine } from "@/components/shell/EngineProvider";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { FilterChip } from "@/components/ui/FilterChip";
import { FlagMarker } from "@/components/ui/FlagMarker";
import { PageHeader } from "@/components/ui/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { getFills, markFill } from "@/lib/api";
import type { FilledPage, FillStatus } from "@/lib/api-types";
import { dateLabel, isWebUrl, shortUrl } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import { FillDrawer, fillTitle } from "./FillDrawer";
import { FillStatusChip } from "./FillStatusChip";

type Filter = "all" | FillStatus;
const HISTORY_EVERY_MS = 15000; // a fill can add a row while this page is open

/**
 * Filled pages history (SPEC Part 2, section 4; design/screens/History.html): every "Fill this page", newest first.
 * Rows still "filled" carry Mark submitted and Abandoned; the engine allows one change only, so a decided row has
 * no buttons. Abandoned asks first (the one you might press on the wrong row). Row click opens the drawer.
 */
export function HistoryScreen() {
  const fills = usePoll(() => getFills(), HISTORY_EVERY_MS);
  const { refresh } = useEngine();
  const { showToast } = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [abandon, setAbandon] = useState<FilledPage | null>(null);

  const all = fills.data ?? [];
  const rows = all.filter((f) => filter === "all" || f.status === filter);
  const count = (k: Filter) => (k === "all" ? all.length : all.filter((f) => f.status === k).length);
  const open = all.find((f) => f.id === openId) ?? null;

  async function mark(f: FilledPage, status: "submitted" | "abandoned") {
    setBusy(true);
    setError(null);
    try {
      await markFill(f.id, status);
      showToast(`${fillTitle(f)} marked as ${status}`);
      setOpenId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      await fills.reload();
      refresh();
    }
  }

  const columns: Column<FilledPage>[] = [
    { key: "date", header: "Date", width: "10fr", render: (f) => <span className="whitespace-nowrap text-label text-jp-ink-2">{dateLabel(f.filled_at)}</span> },
    { key: "co", header: "Company", width: "12fr", render: (f) => f.company ?? <span className="text-jp-ink-2">Unknown</span> },
    { key: "job", header: "Job", width: "20fr", render: (f) => f.job_title ?? <span className="text-jp-ink-2">No job post</span> },
    {
      key: "page",
      header: "Page",
      width: "18fr",
      render: (f) =>
        isWebUrl(f.url) ? (
          <a href={f.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-label font-medium text-jp-brand">
            {shortUrl(f.url, 30)}
          </a>
        ) : (
          <span className="text-label text-jp-ink-2">{shortUrl(f.url, 30)}</span>
        ),
    },
    { key: "res", header: "Resume", width: "7fr", render: (f) => f.resume_id ?? <span className="text-jp-ink-2">None</span> },
    {
      key: "flag",
      header: "Flagged",
      width: "7fr",
      align: "right",
      render: (f) => (f.flagged_count ? <FlagMarker count={f.flagged_count} /> : <span className="text-jp-ink-2">0</span>),
    },
    { key: "status", header: "Status", width: "10fr", render: (f) => <FillStatusChip status={f.status} /> },
    {
      key: "act",
      header: "",
      width: "17fr",
      render: (f) =>
        f.status === "filled" ? (
          <span className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
            <Button size="sm" disabled={busy} onClick={() => void mark(f, "submitted")}>
              Mark submitted
            </Button>
            <Button variant="link" disabled={busy} onClick={() => setAbandon(f)}>
              Abandoned
            </Button>
          </span>
        ) : null,
    },
  ];

  const nOpen = count("filled");

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Filled pages"
        subtitle={fills.data ? (all.length ? `${all.length} pages filled · ${nOpen} waiting for you to mark` : "Nothing filled yet") : "Loading…"}
      />
      {error && <Banner tone="danger" message={error} actionLabel="Reload" onAction={() => { setError(null); void fills.reload(); }} />}
      {fills.error && fills.error.code !== "engine_unreachable" && (
        <Banner tone="danger" message={fills.error.message} actionLabel="Reload" onAction={() => void fills.reload()} />
      )}

      {fills.data && all.length === 0 && (
        <EmptyState
          message="No filled pages yet. Every time you press Fill this page, the page appears here with a screenshot."
          actionLabel="Go to Fill this page"
          actionHref="/"
        />
      )}
      {all.length > 0 && (
        <>
          <div className="flex items-center gap-2">
            {(["all", "filled", "submitted", "abandoned"] as const).map((k) => (
              <FilterChip key={k} label={`${k[0].toUpperCase() + k.slice(1)} ${count(k)}`} active={filter === k} onClick={() => setFilter(k)} />
            ))}
          </div>
          {rows.length === 0 ? (
            <EmptyState message="No pages with this status." actionLabel="Show all" onAction={() => setFilter("all")} />
          ) : (
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(f) => String(f.id)}
              onRowClick={(f) => setOpenId(f.id)}
              selectedKey={openId === null ? null : String(openId)}
              tall
            />
          )}
        </>
      )}

      {open && (
        <FillDrawer
          key={open.id}
          fill={open}
          busy={busy}
          onClose={() => setOpenId(null)}
          onSubmitted={(f) => void mark(f, "submitted")}
          onAbandon={(f) => setAbandon(f)}
        />
      )}

      <ConfirmDialog
        open={abandon !== null}
        title="Mark as abandoned?"
        confirmLabel="Mark abandoned"
        onCancel={() => setAbandon(null)}
        onConfirm={() => {
          const f = abandon!;
          setAbandon(null);
          void mark(f, "abandoned");
        }}
      >
        {abandon && (
          <div className="flex flex-col gap-3 text-jp-ink">
            <div className="rounded-control border border-jp-line bg-jp-ground px-3.5 py-3 leading-normal">
              <b className="font-semibold">{fillTitle(abandon)}</b>
              <br />
              Filled {dateLabel(abandon.filled_at)}
            </div>
            <p>Use this when you closed the form without sending it. It can&apos;t be changed to submitted later.</p>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
