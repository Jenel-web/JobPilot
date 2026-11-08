"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { LockIcon } from "@/components/ui/icons";
import { Tag } from "@/components/ui/Tag";
import { cn } from "@/lib/cn";
import { resumeNames, type AnswerSource, type ReviewItem } from "@/lib/mock/review";
import type { ResumeId } from "@/lib/types";
import { REJECT_REASONS, type Decision, type Draft, type RejectReason } from "./types";

const SOURCE_TAG: Record<Exclude<AnswerSource, "ai">, string> = {
  profile: "from profile",
  bank: "from answer bank",
  local: "filled locally",
};

const inputClass =
  "w-full rounded-control border border-jp-line-strong bg-jp-surface px-2.5 py-1.5 text-label text-jp-ink focus-visible:outline-2 focus-visible:outline-jp-brand";

function Section({ title, children, first }: { title: string; children: React.ReactNode; first?: boolean }) {
  return (
    <section className={cn("flex flex-col gap-2", !first && "border-t border-jp-line-soft pt-3")}>
      <span className="text-sm font-semibold">{title}</span>
      {children}
    </section>
  );
}

/**
 * The right-hand panel of Review batch: why it matched, resume, filled answers,
 * cold email and the job post. Sections follow SPEC.md "Screen 2" in order.
 */
export function ReviewDetail({
  item,
  decision,
  draft,
  rejectOpen,
  onRejectOpenChange,
  onPatch,
  onApprove,
  onReject,
}: {
  item: ReviewItem;
  decision: Decision;
  draft: Draft;
  rejectOpen: boolean;
  onRejectOpenChange: (open: boolean) => void;
  onPatch: (patch: Partial<Draft>) => void;
  onApprove: () => void;
  onReject: (reason: RejectReason) => void;
}) {
  const [showPost, setShowPost] = useState(false);
  const locked = decision === "submitting" || decision === "submitted";
  const approved = decision === "approved" || locked;

  return (
    <div className="flex min-w-0 flex-col overflow-y-auto">
      {/* Header: stays visible while the rest scrolls */}
      <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-jp-line-soft bg-jp-surface px-[22px] py-[18px]">
        <div className="flex min-w-0 flex-col gap-[3px]">
          <span className="font-serif text-[22px] font-medium leading-[1.2]">{item.title}</span>
          <span className="text-label text-jp-ink-2">
            {item.company} · {item.location} · Posted {item.posted} ·{" "}
            <a href="#" target="_blank" rel="noreferrer" className="font-medium text-jp-brand">
              Open on Prosple
            </a>
          </span>
        </div>
        <div className="relative flex shrink-0 gap-2">
          <Button size="sm" disabled={locked} onClick={() => onRejectOpenChange(!rejectOpen)} aria-expanded={rejectOpen}>
            Reject
          </Button>
          <Button size="sm" variant="primary" disabled={locked || approved} onClick={onApprove}>
            {approved ? "Approved ✓" : "Approve"}
          </Button>
          {rejectOpen && (
            <div
              role="menu"
              className="absolute right-0 top-9 z-20 flex w-[220px] flex-col rounded-card border border-jp-line bg-jp-surface p-1.5 shadow-overlay"
            >
              {REJECT_REASONS.map((reason) => (
                <button
                  key={reason}
                  type="button"
                  role="menuitem"
                  onClick={() => onReject(reason)}
                  className={cn(
                    "rounded-control px-2.5 py-2 text-left text-sm hover:bg-jp-ground",
                    reason === "Block this company" && "text-jp-danger",
                  )}
                >
                  {reason}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-3.5 px-[22px] py-[18px]">
        <Section title="Why it matched" first>
          <div className="flex flex-col gap-1 text-sm">
            {item.reasons.map((r) => (
              <span key={r}>{r}</span>
            ))}
          </div>
          {item.missing.length > 0 && (
            <span className="flex flex-wrap items-center gap-1.5 text-label text-jp-ink-2">
              Missing:
              {item.missing.map((m) => (
                <Tag key={m}>{m}</Tag>
              ))}
            </span>
          )}
        </Section>

        <Section title="Resume">
          <div className="flex flex-wrap items-center gap-2 text-label">
            {(["A", "B"] as ResumeId[]).map((id) => {
              const on = draft.resume === id;
              return (
                <button
                  key={id}
                  type="button"
                  disabled={locked}
                  aria-pressed={on}
                  onClick={() => onPatch({ resume: id })}
                  className={cn(
                    "inline-flex h-[30px] items-center rounded-control px-3",
                    on ? "bg-jp-brand font-semibold text-white" : "border border-jp-line-strong bg-jp-surface",
                  )}
                >
                  Resume {id} · {resumeNames[id]}
                </button>
              );
            })}
            <span className="text-jp-ink-2">
              {draft.resume === item.resume
                ? `AI picked this because ${item.resumeReason}`
                : "You changed the AI's pick."}{" "}
              <a href="#" className="font-medium text-jp-brand">
                Preview
              </a>
            </span>
          </div>
        </Section>

        <Section title="Filled answers">
          <div className="grid grid-cols-2 items-center gap-x-3.5 gap-y-1.5 text-label">
            {item.answers.map((a) => {
              const value = draft.answers[a.question] ?? a.answer;
              return (
                <div key={a.question} className="contents">
                  <span className="text-jp-ink-2">{a.question}</span>
                  {a.source === "local" ? (
                    <span className="inline-flex items-center gap-2 rounded-control border border-jp-line bg-jp-surface px-2.5 py-1.5">
                      {value}
                      <span className="inline-flex items-center gap-1 text-xs text-jp-ink-2">
                        <LockIcon /> {SOURCE_TAG.local}
                      </span>
                    </span>
                  ) : (
                    <span
                      className={cn(
                        "flex items-center gap-2 rounded-control border px-2.5 py-1.5",
                        a.source === "ai"
                          ? "border-jp-amber-border bg-jp-amber-bg"
                          : "border-jp-line bg-jp-surface",
                      )}
                    >
                      <input
                        data-answer-input
                        value={value}
                        disabled={locked}
                        aria-label={a.question}
                        onChange={(e) => onPatch({ answers: { ...draft.answers, [a.question]: e.target.value } })}
                        className="min-w-0 flex-1 bg-transparent text-label text-jp-ink outline-none"
                      />
                      <span
                        className={cn(
                          "shrink-0 whitespace-nowrap text-xs",
                          a.source === "ai" ? "text-jp-amber-text" : "text-jp-ink-2",
                        )}
                      >
                        {a.source === "ai" ? "▲ AI guess, check this" : SOURCE_TAG[a.source]}
                      </span>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {item.answers.some((a) => a.source === "ai") && (
            <Checkbox
              checked={draft.saveToBank}
              onChange={(v) => onPatch({ saveToBank: v })}
              label="Save to answer bank"
            />
          )}
        </Section>

        <Section title="Form screenshot">
          <div className="flex h-[72px] w-[120px] items-center justify-center rounded-control border border-jp-line bg-jp-ground text-center text-xs text-jp-ink-2">
            Form screenshot
          </div>
        </Section>

        <Section title="Cold email">
          {item.contact && item.email ? (
            <>
              <div className="flex flex-col gap-0.5 text-label text-jp-ink-2">
                <span className="font-medium text-jp-ink">
                  {item.contact.name}, {item.contact.title} · <span className="text-jp-status-submitted">✓ Verified</span>
                </span>
                <span>Found via: {item.contact.foundVia}</span>
              </div>
              <div className="flex items-center gap-2">
                <Tag>{item.email.tier}</Tag>
                <Checkbox
                  checked={draft.skipEmail}
                  onChange={(v) => onPatch({ skipEmail: v })}
                  label="Don't send an email for this job"
                />
              </div>
              <input
                aria-label="Email subject"
                value={draft.emailSubject}
                disabled={locked || draft.skipEmail}
                onChange={(e) => onPatch({ emailSubject: e.target.value })}
                className={inputClass}
              />
              <textarea
                aria-label="Email body"
                rows={4}
                value={draft.emailBody}
                disabled={locked || draft.skipEmail}
                onChange={(e) => onPatch({ emailBody: e.target.value })}
                className={cn(inputClass, "resize-y leading-normal")}
              />
              <span className="text-xs text-jp-ink-2">Facts used: {item.email.factsUsed.join(" · ")}</span>
            </>
          ) : (
            <div className="flex flex-col gap-2 rounded-control bg-jp-muted-bg p-3 text-label text-jp-ink-2">
              No verified contact found
              <input
                aria-label="Paste an email address"
                placeholder="Paste an email address (it still has to be verified)"
                value={draft.manualEmail}
                onChange={(e) => onPatch({ manualEmail: e.target.value })}
                className={inputClass}
              />
            </div>
          )}
        </Section>

        <Section title="Job post">
          <button
            type="button"
            onClick={() => setShowPost((s) => !s)}
            className="self-start text-label font-medium text-jp-brand"
          >
            {showPost ? "Hide full post" : "Show full post"}
          </button>
          {showPost && (
            <p className="text-label leading-normal text-jp-ink-2">
              Mock text standing in for the full Prosple job description of {item.title} at {item.company}. The real
              post is saved with the job when it is scraped.
            </p>
          )}
        </Section>

        <div className="flex items-center justify-between gap-3 rounded-card bg-jp-brand-tint px-3.5 py-3 text-label">
          <span>
            {decision === "submitted"
              ? "Submitted."
              : approved
                ? "Approved. It goes out with the rest of the batch."
                : "Approve this job, then submit with the rest of the batch."}
          </span>
          <span className="font-semibold text-jp-brand">Keys: J/K next · A approve · R reject · E edit</span>
        </div>
      </div>
    </div>
  );
}
