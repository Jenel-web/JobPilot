"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { Select } from "@/components/ui/Select";
import { StatusChip, statusLabel } from "@/components/ui/StatusChip";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { applications, STATUS_ORDER, type AppRow, type EmailState } from "@/lib/mock/applications";
import { scoreTextClass } from "@/lib/score";
import type { Status } from "@/lib/types";

type TabId = "all" | "submitted" | "manual" | "failed" | "interviews";

// Optional columns the Column picker can switch on (SPEC.md Screen 3).
const OPTIONAL = ["location", "type", "contact", "links"] as const;
type Optional = (typeof OPTIONAL)[number];
const OPTIONAL_LABEL: Record<Optional, string> = { location: "Location", type: "Type", contact: "Contact", links: "Links" };

const EMAIL_CLASS: Record<EmailState, string> = {
  "Sent ✓": "text-jp-status-submitted",
  Queued: "text-jp-ink-2",
  Bounced: "text-jp-danger",
  None: "text-jp-ink-2",
};

const inputClass =
  "h-8 rounded-control border border-jp-line-strong bg-jp-surface px-2.5 text-label text-jp-ink placeholder:text-jp-ink-2 focus-visible:outline-2 focus-visible:outline-jp-brand";

function csvCell(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

/** Applications: the full history of every job JobPilot touched. A big table plus a detail drawer. */
export function ApplicationsBoard() {
  const { showToast } = useToast();
  const [tab, setTab] = useState<TabId>("all");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [scoreFilter, setScoreFilter] = useState("all");
  const [resumeFilter, setResumeFilter] = useState("all");
  const [shown, setShown] = useState<Optional[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  // Edits the user makes in the drawer or on the manual tab (kept in the browser for the mock).
  const [statusEdits, setStatusEdits] = useState<Record<string, Status>>({});
  const [noteEdits, setNoteEdits] = useState<Record<string, string>>({});

  const statusOf = (r: AppRow): Status => statusEdits[r.id] ?? r.status;

  const counts = useMemo(
    () => ({
      manual: applications.filter((r) => (statusEdits[r.id] ?? r.status) === "manual").length,
      failed: applications.filter((r) => (statusEdits[r.id] ?? r.status) === "failed").length,
    }),
    [statusEdits],
  );

  const rows = applications.filter((r) => {
    const s = statusOf(r);
    if (tab === "submitted" && s !== "submitted") return false;
    if (tab === "manual" && s !== "manual") return false;
    if (tab === "failed" && s !== "failed") return false;
    if (tab === "interviews" && s !== "interview" && s !== "offer") return false;
    if (statusFilter !== "all" && s !== statusFilter) return false;
    if (resumeFilter !== "all" && r.resume !== resumeFilter) return false;
    if (scoreFilter === "80" && r.score < 80) return false;
    if (scoreFilter === "60" && (r.score < 60 || r.score >= 80)) return false;
    if (scoreFilter === "low" && r.score >= 60) return false;
    const q = query.trim().toLowerCase();
    return !q || r.company.toLowerCase().includes(q) || r.role.toLowerCase().includes(q);
  });

  const open = applications.find((r) => r.id === openId) ?? null;

  const markApplied = (r: AppRow) => {
    setStatusEdits((prev) => ({ ...prev, [r.id]: "submitted" }));
    showToast(`${r.company} marked as applied`, "Saved");
  };

  const exportCsv = () => {
    const header = ["Date", "Company", "Role", "Location", "Type", "Score", "Resume", "Status", "Email"];
    const lines = rows.map((r) =>
      [r.date, r.company, r.role, r.location, r.type, String(r.score), r.resume, statusLabel(statusOf(r)), r.email]
        .map(csvCell)
        .join(","),
    );
    const blob = new Blob([[header.map(csvCell).join(","), ...lines].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "applications.csv";
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Exported ${rows.length} rows`, "Saved");
  };

  const columns: Column<AppRow>[] = [
    { key: "date", header: "Date", width: "64px", render: (r) => <span className="text-jp-ink-2">{r.date}</span> },
    { key: "company", header: "Company", width: "1.1fr", render: (r) => r.company },
    { key: "role", header: "Role", width: "1.4fr", render: (r) => r.role },
    ...(shown.includes("location")
      ? [{ key: "location", header: "Location", width: "1fr", render: (r: AppRow) => r.location }]
      : []),
    ...(shown.includes("type") ? [{ key: "type", header: "Type", width: "90px", render: (r: AppRow) => r.type }] : []),
    {
      key: "score",
      header: "Score",
      width: "70px",
      render: (r) => <span className={cn("font-semibold", scoreTextClass(r.score))}>{r.score}</span>,
    },
    { key: "resume", header: "Resume", width: "60px", render: (r) => r.resume },
    {
      key: "email",
      header: "Email",
      width: "70px",
      render: (r) => <span className={EMAIL_CLASS[r.email]}>{r.email}</span>,
    },
    ...(shown.includes("contact")
      ? [{ key: "contact", header: "Contact", width: "1fr", render: (r: AppRow) => r.contact ?? "—" }]
      : []),
    ...(shown.includes("links")
      ? [
          {
            key: "links",
            header: "Links",
            width: "70px",
            render: (r: AppRow) => (
              <a href="#" onClick={(e) => e.stopPropagation()} className="text-jp-brand" aria-label={`Open ${r.company} post`}>
                Post ↗
              </a>
            ),
          },
        ]
      : []),
    ...(tab === "manual"
      ? [{ key: "reason", header: "Why manual", width: "1fr", render: (r: AppRow) => r.manualReason ?? "—" }]
      : []),
    {
      key: "status",
      header: "Status",
      width: tab === "manual" ? "90px" : "1fr",
      render: (r) => <StatusChip status={statusOf(r)} size="sm" />,
    },
    ...(tab === "manual"
      ? [
          {
            key: "actions",
            header: "Action",
            width: "230px",
            render: (r: AppRow) =>
              statusOf(r) === "manual" ? (
                <span className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                  <Button href="#" external variant="primary" size="xs">
                    Open &amp; apply
                  </Button>
                  <Button size="xs" onClick={() => markApplied(r)}>
                    Mark as applied
                  </Button>
                </span>
              ) : null,
          },
        ]
      : []),
  ];

  const tabs = [
    { id: "all", label: "All" },
    { id: "submitted", label: "Submitted" },
    { id: "manual", label: `Needs manual apply (${counts.manual})` },
    { id: "failed", label: `Failed (${counts.failed})` },
    { id: "interviews", label: "Interviews" },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3.5">
      <PageHeader
        title="Applications"
        subtitle={`${applications.length} total · every job JobPilot has touched`}
        actions={
          <>
            <div className="relative">
              <Button onClick={() => setPickerOpen((o) => !o)} aria-expanded={pickerOpen}>
                Column picker
              </Button>
              {pickerOpen && (
                <div className="absolute right-0 top-10 z-20 flex w-[200px] flex-col gap-2 rounded-card border border-jp-line bg-jp-surface p-3 shadow-overlay">
                  {OPTIONAL.map((c) => (
                    <Checkbox
                      key={c}
                      checked={shown.includes(c)}
                      onChange={(v) => setShown((prev) => (v ? [...prev, c] : prev.filter((x) => x !== c)))}
                      label={OPTIONAL_LABEL[c]}
                      className="text-sm text-jp-ink"
                    />
                  ))}
                </div>
              )}
            </div>
            <Button onClick={exportCsv}>Export CSV</Button>
          </>
        }
      />

      <div className="flex items-center justify-between gap-3 border-b border-jp-line">
        <Tabs tabs={tabs} active={tab} onChange={(id) => setTab(id as TabId)} />
        <div className="flex items-center gap-2 pb-1.5">
          <input
            aria-label="Search company or role"
            placeholder="Search company or role"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className={cn(inputClass, "w-[180px]")}
          />
          <Select
            label="Status"
            value={statusFilter}
            onChange={setStatusFilter}
            options={[{ value: "all", label: "Status" }, ...STATUS_ORDER.map((s) => ({ value: s, label: statusLabel(s) }))]}
          />
          <Select
            label="Score"
            value={scoreFilter}
            onChange={setScoreFilter}
            options={[
              { value: "all", label: "Score" },
              { value: "80", label: "80 and above" },
              { value: "60", label: "60 to 79" },
              { value: "low", label: "Under 60" },
            ]}
          />
          <Select
            label="Resume"
            value={resumeFilter}
            onChange={setResumeFilter}
            options={[
              { value: "all", label: "Resume" },
              { value: "A", label: "Resume A" },
              { value: "B", label: "Resume B" },
            ]}
          />
        </div>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="No applications match these filters." actionLabel="Clear filters" onAction={() => {
          setTab("all");
          setQuery("");
          setStatusFilter("all");
          setScoreFilter("all");
          setResumeFilter("all");
        }} />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} onRowClick={(r) => setOpenId(r.id)} selectedKey={openId} />
      )}

      <Drawer
        open={open !== null}
        onClose={() => setOpenId(null)}
        label="Application details"
        header={
          open && (
            <>
              <span className="font-serif text-[22px] font-medium leading-[1.2]">{open.role}</span>
              <span className="text-label text-jp-ink-2">
                {open.company} · {open.location} · {open.type}
              </span>
              <div className="mt-1 flex items-center gap-2">
                <StatusChip status={statusOf(open)} />
                <Select
                  label="Change status"
                  value={statusOf(open)}
                  onChange={(v) => {
                    setStatusEdits((prev) => ({ ...prev, [open.id]: v as Status }));
                    showToast(`Status set to ${statusLabel(v as Status)}`, "Saved");
                  }}
                  options={STATUS_ORDER.map((s) => ({ value: s, label: statusLabel(s) }))}
                />
                <ScoreBadge score={open.score} size={36} />
              </div>
            </>
          )
        }
      >
        {open && (
          <>
            <section className="flex flex-col gap-2.5">
              <span className="text-sm font-semibold">Timeline</span>
              {open.timeline.map((e, i) => (
                <div key={i} className="flex gap-3 text-label">
                  <span className="tabular w-16 shrink-0 text-jp-ink-2">{e.date}</span>
                  <span>{e.text}</span>
                </div>
              ))}
            </section>
            <section className="flex flex-col gap-2 border-t border-jp-line-soft pt-3.5">
              <span className="text-sm font-semibold">Notes</span>
              <textarea
                aria-label="Notes"
                rows={3}
                value={noteEdits[open.id] ?? open.notes}
                onChange={(e) => setNoteEdits((prev) => ({ ...prev, [open.id]: e.target.value }))}
                onBlur={() => showToast("Notes saved", "Saved")}
                placeholder="Your own notes, e.g. HR called, interview Nov 20"
                className="min-h-14 rounded-control border border-jp-line-strong bg-jp-surface px-3 py-2.5 text-sm text-jp-ink focus-visible:outline-2 focus-visible:outline-jp-brand"
              />
            </section>
            <section className="flex flex-col gap-2 border-t border-jp-line-soft pt-3.5">
              <span className="text-sm font-semibold">Email</span>
              <span className="text-label text-jp-ink-2">
                {open.emailLine ?? "No email for this application."}
                {open.email === "Sent ✓" && (
                  <>
                    {" · "}
                    <a href="#" className="font-medium text-jp-brand">
                      View in Gmail
                    </a>
                  </>
                )}
              </span>
            </section>
            {open.answers.length > 0 && (
              <section className="flex flex-col gap-2 border-t border-jp-line-soft pt-3.5">
                <span className="text-sm font-semibold">Answers sent</span>
                <div className="grid grid-cols-2 gap-x-3.5 gap-y-1.5 text-label">
                  {open.answers.map((a) => (
                    <div key={a.question} className="contents">
                      <span className="text-jp-ink-2">{a.question}</span>
                      <span>{a.answer}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
            <section className="flex flex-col gap-2 border-t border-jp-line-soft pt-3.5">
              <span className="text-sm font-semibold">Screenshot</span>
              <div className="flex h-[72px] w-[120px] items-center justify-center rounded-control border border-jp-line bg-jp-ground text-center text-xs text-jp-ink-2">
                Submitted form
              </div>
            </section>
          </>
        )}
      </Drawer>
    </div>
  );
}
