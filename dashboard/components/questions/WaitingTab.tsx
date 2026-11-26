"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { TextArea } from "@/components/ui/TextArea";
import type { Kind, Scope, UnknownAnswerIn, UnknownQuestion } from "@/lib/api-types";
import { cn } from "@/lib/cn";
import { isWebUrl, plural, shortUrl } from "@/lib/format";
import { KIND_OPTIONS, SCOPE_OPTIONS } from "@/lib/labels";

/** "Seen 2 times · last on careers.shopee.sg/apply" (the engine keeps only the last page it was seen on). */
function SeenLine({ q }: { q: UnknownQuestion }) {
  return (
    <span className="text-label text-jp-ink-2">
      Seen {plural(q.times_seen, "time")}
      {q.page_url && (
        <>
          {" · last on "}
          {isWebUrl(q.page_url) ? (
            <a href={q.page_url} target="_blank" rel="noreferrer" className="font-medium text-jp-brand">
              {shortUrl(q.page_url)}
            </a>
          ) : (
            shortUrl(q.page_url)
          )}
        </>
      )}
    </span>
  );
}

function category(q: UnknownQuestion): string {
  return q.protected ? "Legal and eligibility" : `Form field · ${q.field_type ?? "text"}`;
}

/** The answer form for the selected question. `kind` starts empty on purpose: the engine wants you to choose it. */
function AnswerCard({
  q,
  saving,
  onSave,
}: {
  q: UnknownQuestion;
  saving: boolean;
  onSave: (body: UnknownAnswerIn) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [kind, setKind] = useState<Kind | "">(q.protected ? "protected" : "");
  const [scope, setScope] = useState<Scope>("any");
  const [city, setCity] = useState("");
  const ready = Boolean(answer.trim() && kind && (scope !== "city" || city.trim()));

  const kindOptions = [
    ...(q.protected ? [] : [{ value: "", label: "Choose how it is used…" }]),
    ...KIND_OPTIONS.filter((k) => !q.protected || k.value === "protected").map((k) => ({
      value: k.value,
      label: `${k.label}: ${k.help.split(";")[0]}`,
    })),
  ];

  return (
    <div className="flex flex-col gap-3.5 rounded-card border border-l-[3px] border-jp-line border-l-jp-amber bg-jp-surface px-[22px] py-5">
      <span className="text-label text-jp-ink-2">{category(q)}</span>
      <span className="text-[18px] font-semibold leading-snug">{q.question}</span>
      <SeenLine q={q} />
      {q.protected && (
        <div className="rounded-card border border-jp-amber-border bg-jp-amber-bg px-4 py-3 text-sm text-jp-amber-text">
          <b className="font-semibold">You must answer this yourself.</b> Legal and eligibility questions never get AI
          help. Your answer is saved as protected and filled word for word.
        </div>
      )}
      {q.options.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-label font-medium text-jp-ink-2">The form&apos;s choices</span>
          <Select
            label="Pick one of the form's choices"
            value={q.options.includes(answer) ? answer : ""}
            onChange={setAnswer}
            className="h-9"
            options={[{ value: "", label: "Pick one, or type below…" }, ...q.options.map((o) => ({ value: o, label: o }))]}
          />
        </div>
      )}
      <TextArea
        label="Your answer"
        value={answer}
        onChange={setAnswer}
        rows={3}
        placeholder="Type the answer once. It is reused on every form that asks this."
      />
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="text-label font-medium text-jp-ink-2">Kind</span>
          <Select label="Kind" value={kind} onChange={(v) => setKind(v as Kind | "")} className="h-9" options={kindOptions} />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-label font-medium text-jp-ink-2">Location scope</span>
          <Select label="Location scope" value={scope} onChange={(v) => setScope(v as Scope)} options={SCOPE_OPTIONS} className="h-9" />
        </label>
      </div>
      {scope === "city" && <Field label="City" value={city} onChange={setCity} />}
      <div className="flex items-center justify-between gap-3 border-t border-jp-line-soft pt-3">
        <span className="text-label text-jp-ink-2">Saved answers are reused on future forms.</span>
        <Button
          variant="primary"
          disabled={!ready || saving}
          onClick={() => onSave({ answer: answer.trim(), kind: kind as Kind, scope, city: city.trim() })}
        >
          {saving ? "Saving…" : "Save answer"}
        </Button>
      </div>
    </div>
  );
}

/**
 * Waiting: questions the bot could not answer. The selected one is a form on the left; the others are cards
 * on the right (design/screens/Questions.html, frame 1). `focusId` selects a question on arrival
 * (the Fill page's "Answer the new question" links here with ?id=).
 */
export function WaitingTab({
  items,
  saving,
  focusId,
  onSave,
}: {
  items: UnknownQuestion[];
  saving: boolean;
  focusId: number | null;
  onSave: (q: UnknownQuestion, body: UnknownAnswerIn) => void;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  if (items.length === 0) {
    return (
      <EmptyState
        message="No questions waiting. When a form asks something JobPilot has no answer for, it appears here."
        actionLabel="Open Answer bank"
        actionHref="/answers"
      />
    );
  }
  const selected = items.find((q) => q.id === (picked ?? focusId)) ?? items[0];
  const others = items.filter((q) => q.id !== selected.id);

  return (
    <div className="grid grid-cols-2 items-start gap-4">
      <AnswerCard key={selected.id} q={selected} saving={saving} onSave={(body) => onSave(selected, body)} />
      <div className="flex flex-col gap-3">
        {others.map((q) => (
          <button
            key={q.id}
            type="button"
            onClick={() => setPicked(q.id)}
            className={cn(
              "flex flex-col gap-2 rounded-card border border-jp-line bg-jp-surface px-[18px] py-4 text-left",
              "hover:border-jp-line-strong focus-visible:outline-2 focus-visible:outline-jp-brand",
            )}
          >
            <span className="text-label text-jp-ink-2">{category(q)}</span>
            <span className="line-clamp-3 text-[15px] font-semibold leading-snug" title={q.question}>
              {q.question}
            </span>
            <SeenLine q={q} />
            <span className="text-label text-jp-ink-2">
              {q.protected ? "You must answer this yourself." : "Waiting for your answer."}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
