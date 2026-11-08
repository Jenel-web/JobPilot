"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useShell } from "@/components/shell/ShellProvider";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { FilterChip } from "@/components/ui/FilterChip";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tabs } from "@/components/ui/Tabs";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { initiallyApproved, reviewQueue, type ReviewItem } from "@/lib/mock/review";
import { ReviewDetail } from "./ReviewDetail";
import { ReviewQueueRow } from "./ReviewQueueRow";
import type { Decision, Draft, RejectReason } from "./types";

type Filter = "all" | "flagged" | "score80" | "internship" | "fulltime";

const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: "all", label: "All" },
  { id: "flagged", label: "Flagged only" },
  { id: "score80", label: "Score 80+" },
  { id: "internship", label: "Internship" },
  { id: "fulltime", label: "Full-time" },
];

const flagCount = (item: ReviewItem): number => item.answers.filter((a) => a.source === "ai").length;

function matchesFilter(item: ReviewItem, filter: Filter): boolean {
  switch (filter) {
    case "flagged":
      return flagCount(item) > 0;
    case "score80":
      return item.score >= 80;
    case "internship":
      return item.type === "Internship";
    case "fulltime":
      return item.type === "Full-time";
    default:
      return true;
  }
}

function initialDraft(item: ReviewItem): Draft {
  return {
    resume: item.resume,
    answers: {},
    saveToBank: false,
    emailSubject: item.email?.subject ?? "",
    emailBody: item.email?.body ?? "",
    skipEmail: false,
    manualEmail: "",
  };
}

/**
 * Review batch: approve or reject queued applications, then submit the approved
 * ones. This is where the 10 minutes a day are spent (SPEC.md Screen 2).
 * Mock: all state lives in the browser and nothing is sent anywhere.
 */
export function ReviewBoard() {
  const { mode, stopped } = useShell();
  const { showToast } = useToast();

  const [decisions, setDecisions] = useState<Record<string, Decision>>(() =>
    Object.fromEntries(reviewQueue.map((i) => [i.id, initiallyApproved.includes(i.id) ? "approved" : "queued"])),
  );
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(reviewQueue.map((i) => [i.id, initialDraft(i)])),
  );
  const [selectedId, setSelectedId] = useState<string>(reviewQueue[0].id);
  const [checked, setChecked] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [tab, setTab] = useState<"applications" | "emails">("applications");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  const pending = reviewQueue.filter((i) => decisions[i.id] === "queued" || decisions[i.id] === "approved");
  const emailItems = pending.filter((i) => i.email && !drafts[i.id].skipEmail);
  const flaggedCount = pending.filter((i) => flagCount(i) > 0).length;
  const approvedItems = reviewQueue.filter((i) => decisions[i.id] === "approved");
  const approvedEmails = approvedItems.filter((i) => i.email && !drafts[i.id].skipEmail);

  const visible = useMemo(() => reviewQueue.filter((i) => matchesFilter(i, filter)), [filter]);
  const selected = visible.find((i) => i.id === selectedId) ?? visible[0] ?? null;

  const setDecision = useCallback((ids: string[], decision: Decision) => {
    setDecisions((prev) => ({ ...prev, ...Object.fromEntries(ids.map((id) => [id, decision])) }));
  }, []);

  const patchDraft = (id: string, patch: Partial<Draft>) =>
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  const move = useCallback(
    (delta: number) => {
      if (visible.length === 0) return;
      const index = Math.max(0, visible.findIndex((i) => i.id === selected?.id));
      const next = visible[Math.min(visible.length - 1, Math.max(0, index + delta))];
      setSelectedId(next.id);
      setRejectOpen(false);
    },
    [visible, selected],
  );

  const approve = useCallback(
    (id: string) => {
      if (decisions[id] !== "queued") return;
      setDecision([id], "approved");
      showToast("Approved", "Saved");
    },
    [decisions, setDecision, showToast],
  );

  const reject = (item: ReviewItem, reason: RejectReason) => {
    setDecision([item.id], "rejected");
    setRejectOpen(false);
    showToast(
      reason === "Block this company" ? `${item.company} added to the blocklist` : `Rejected: ${reason}`,
      "Saved",
    );
    move(1);
  };

  const approveAllUnflagged = () => {
    const ids = reviewQueue.filter((i) => decisions[i.id] === "queued" && flagCount(i) === 0).map((i) => i.id);
    setDecision(ids, "approved");
    showToast(ids.length ? `${ids.length} jobs approved` : "Nothing left to approve", ids.length ? "Saved" : undefined);
  };

  const startSubmit = () => {
    setConfirmOpen(false);
    setDecision(
      approvedItems.map((i) => i.id),
      "submitting",
    );
  };

  // Finish the (fake) submit after a moment. In mock and dry run NOTHING is submitted.
  const submitting = Object.values(decisions).includes("submitting");
  useEffect(() => {
    if (!submitting) return;
    const timer = setTimeout(() => {
      setDecisions((prev) =>
        Object.fromEntries(
          Object.entries(prev).map(([id, d]) => [id, d === "submitting" ? (mode === "live" ? "submitted" : "approved") : d]),
        ),
      );
      showToast(
        mode === "live"
          ? "Submitted. Confirmations saved."
          : `${mode === "mock" ? "Mock" : "Dry run"}: nothing was submitted or sent.`,
      );
    }, 1200);
    return () => clearTimeout(timer);
  }, [submitting, mode, showToast]);

  // Keyboard shortcuts: J/K next/previous, A approve, R reject menu, E edit first answer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (confirmOpen || tab !== "applications" || !selected) return;
      const key = e.key.toLowerCase();
      if (key === "j") move(1);
      else if (key === "k") move(-1);
      else if (key === "a") approve(selected.id);
      else if (key === "r") setRejectOpen(true);
      else if (key === "e") {
        e.preventDefault();
        document.querySelector<HTMLInputElement>("[data-answer-input]")?.focus();
      } else if (key === "escape") setRejectOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmOpen, tab, selected, move, approve]);

  const allChecked = visible.length > 0 && visible.every((i) => checked.includes(i.id));
  const subtitle = `${pending.length} applications · ${emailItems.length} emails · ${flaggedCount} flagged`;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3.5">
      <PageHeader
        title="Review batch"
        subtitle={subtitle}
        actions={
          <>
            <Button onClick={approveAllUnflagged}>Approve all unflagged</Button>
            <Button
              variant="primary"
              disabled={approvedItems.length === 0 || submitting || stopped}
              onClick={() => setConfirmOpen(true)}
            >
              Submit approved ({approvedItems.length})
            </Button>
          </>
        }
      />

      <div className="flex items-center justify-between gap-3">
        <Tabs
          variant="boxed"
          active={tab}
          onChange={(id) => setTab(id as "applications" | "emails")}
          tabs={[
            { id: "applications", label: `Applications (${pending.length})` },
            { id: "emails", label: `Emails (${emailItems.length})` },
          ]}
        />
        {tab === "applications" && (
          <div className="flex gap-1.5">
            {FILTERS.map((f) => (
              <FilterChip key={f.id} label={f.label} active={filter === f.id} onClick={() => setFilter(f.id)} />
            ))}
          </div>
        )}
      </div>

      {tab === "emails" ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto rounded-card border border-jp-line bg-jp-surface">
          {emailItems.length === 0 ? (
            <div className="p-4">
              <EmptyState message="No emails waiting for review." />
            </div>
          ) : (
            emailItems.map((i) => (
              <div key={i.id} className="flex items-center justify-between gap-4 border-b border-jp-line-soft px-4 py-3">
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-sm font-semibold">
                    {i.contact?.name} · <span className="font-normal text-jp-ink-2">{i.contact?.title}</span>
                  </span>
                  <span className="text-label text-jp-ink-2">
                    {i.company} · {i.title}
                  </span>
                  <span className="truncate text-label">{drafts[i.id].emailSubject}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <Tag>{i.email?.tier}</Tag>
                  <Button href="/emails" variant="link">
                    Open in Emails
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[40fr_60fr] overflow-hidden rounded-card border border-jp-line bg-jp-surface">
          <div className="flex min-h-0 min-w-0 flex-col border-r border-jp-line">
            <div className="flex items-center gap-2.5 border-b border-jp-line px-3.5 py-2 text-xs font-medium text-jp-ink-2">
              {checked.length > 0 ? (
                <>
                  <span className="tabular">{checked.length} selected</span>
                  <Button
                    size="xs"
                    onClick={() => {
                      setDecision(
                        checked.filter((id) => decisions[id] === "queued"),
                        "approved",
                      );
                      showToast(`${checked.length} jobs approved`, "Saved");
                      setChecked([]);
                    }}
                  >
                    Approve selected
                  </Button>
                  <Button
                    size="xs"
                    onClick={() => {
                      setDecision(checked, "rejected");
                      showToast(`${checked.length} jobs rejected`, "Saved");
                      setChecked([]);
                    }}
                  >
                    Reject selected
                  </Button>
                </>
              ) : (
                <Checkbox
                  checked={allChecked}
                  onChange={(v) => setChecked(v ? visible.map((i) => i.id) : [])}
                  label="Select all · sorted by score"
                  className="text-xs font-medium"
                />
              )}
            </div>
            <div role="listbox" aria-label="Queued applications" className="min-h-0 flex-1 overflow-y-auto">
              {visible.length === 0 ? (
                <div className="p-4">
                  <EmptyState message="No jobs match this filter." actionLabel="Show all" onAction={() => setFilter("all")} />
                </div>
              ) : (
                visible.map((item) => (
                  <ReviewQueueRow
                    key={item.id}
                    item={item}
                    decision={decisions[item.id]}
                    flags={flagCount(item)}
                    resumeId={drafts[item.id].resume}
                    selected={selected?.id === item.id}
                    checked={checked.includes(item.id)}
                    onSelect={() => {
                      setSelectedId(item.id);
                      setRejectOpen(false);
                    }}
                    onCheck={(v) => setChecked((prev) => (v ? [...prev, item.id] : prev.filter((id) => id !== item.id)))}
                  />
                ))
              )}
            </div>
          </div>

          {selected ? (
            <ReviewDetail
              key={selected.id}
              item={selected}
              decision={decisions[selected.id]}
              draft={drafts[selected.id]}
              rejectOpen={rejectOpen}
              onRejectOpenChange={setRejectOpen}
              onPatch={(patch) => patchDraft(selected.id, patch)}
              onApprove={() => approve(selected.id)}
              onReject={(reason) => reject(selected, reason)}
            />
          ) : (
            <div className="p-6">
              <EmptyState message="Pick a job on the left to see why it matched." />
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title={`Submit ${approvedItems.length} approved ${approvedItems.length === 1 ? "job" : "jobs"}?`}
        confirmLabel={`Submit ${approvedItems.length} ${approvedItems.length === 1 ? "job" : "jobs"}`}
        tone="primary"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={startSubmit}
      >
        <ul className="mb-2 flex list-disc flex-col gap-0.5 pl-5">
          {approvedItems.map((i) => (
            <li key={i.id}>
              {i.title} · {i.company}
            </li>
          ))}
        </ul>
        {approvedItems.length} {approvedItems.length === 1 ? "application" : "applications"} and {approvedEmails.length}{" "}
        {approvedEmails.length === 1 ? "email" : "emails"} will go out now.{" "}
        {mode === "live"
          ? "This cannot be undone."
          : `Mode is ${mode === "mock" ? "MOCK" : "DRY RUN"}, so nothing is actually submitted or sent.`}
      </ConfirmDialog>
    </div>
  );
}
