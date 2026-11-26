"use client";

import { useState } from "react";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { Tag } from "@/components/ui/Tag";
import { TextArea } from "@/components/ui/TextArea";
import type { Kind, SavedAnswer, Scope } from "@/lib/api-types";
import { dateLabel } from "@/lib/format";
import { KIND_OPTIONS, SCOPE_OPTIONS } from "@/lib/labels";

export type AnswerDraft = { question: string; answer: string; kind: Kind; scope: Scope; city: string };

function draftOf(a: SavedAnswer | null): AnswerDraft {
  if (!a) return { question: "", answer: "", kind: "fixed", scope: "any", city: "" };
  const scope = (["any", "city", "remote", "abroad"].includes(a.location_scope) ? a.location_scope : "any") as Scope;
  return { question: a.question, answer: a.answer, kind: a.kind, scope, city: a.city };
}

/**
 * Add or edit one saved answer (design/screens/AnswerBank.html, frame 2). The question text of a saved answer
 * cannot change (the engine keeps it as the answer's identity), so it is editable only when adding.
 * The kind decides how the filler uses the answer, so each kind has one line of help.
 */
export function AnswerDrawer({
  answer,
  open,
  saving,
  error,
  onClose,
  onSave,
  onDelete,
}: {
  /** The answer to edit, or null to add a new one. */
  answer: SavedAnswer | null;
  open: boolean;
  saving: boolean;
  /** An engine error about this answer (shown inside the drawer). */
  error: string | null;
  onClose: () => void;
  onSave: (draft: AnswerDraft) => void;
  onDelete: (answer: SavedAnswer) => void;
}) {
  const [draft, setDraft] = useState<AnswerDraft>(() => draftOf(answer));
  const set = (patch: Partial<AnswerDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const ready = Boolean(draft.question.trim() && draft.answer.trim() && (draft.scope !== "city" || draft.city.trim()));
  const adding = answer === null;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      label={adding ? "Add an answer" : "Edit answer"}
      header={<h2 className="text-[20px] font-semibold">{adding ? "Add an answer" : "Edit answer"}</h2>}
    >
      {error && <Banner tone="danger" message={error} actionLabel="Close" onAction={onClose} />}
      {adding ? (
        <Field label="Question" value={draft.question} onChange={(v) => set({ question: v })} />
      ) : (
        <div className="flex flex-col gap-1.5">
          <span className="text-label font-medium text-jp-ink-2">Question</span>
          <span className="text-[15px] font-semibold leading-snug">{draft.question}</span>
        </div>
      )}
      <TextArea label="Answer" value={draft.answer} onChange={(v) => set({ answer: v })} rows={4} />
      <label className="flex flex-col gap-1.5">
        <span className="text-label font-medium text-jp-ink-2">Kind</span>
        <Select
          label="Kind"
          value={draft.kind}
          onChange={(v) => set({ kind: v as Kind })}
          options={KIND_OPTIONS.map((k) => ({ value: k.value, label: k.label }))}
          className="h-9"
        />
        <span className="text-label leading-normal text-jp-ink-2">
          {KIND_OPTIONS.map((k) => (
            <span key={k.value}>
              <b className="font-semibold">{k.label}:</b> {k.help}.{" "}
            </span>
          ))}
          Changes to a protected answer need a confirm.
        </span>
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="text-label font-medium text-jp-ink-2">Location scope</span>
          <Select label="Location scope" value={draft.scope} onChange={(v) => set({ scope: v as Scope })} options={SCOPE_OPTIONS} className="h-9" />
        </label>
        {draft.scope === "city" && <Field label="City" value={draft.city} onChange={(v) => set({ city: v })} />}
      </div>
      {answer && answer.also_asked_as.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-label font-medium text-jp-ink-2">Also asked as</span>
          <div className="flex flex-wrap gap-1.5">
            {answer.also_asked_as.map((w) => (
              <Tag key={w}>{w}</Tag>
            ))}
          </div>
          <span className="text-label text-jp-ink-2">Approved on Questions → Wordings.</span>
        </div>
      )}
      {answer && (
        <span className="text-label text-jp-ink-2">
          Used {answer.times_used} {answer.times_used === 1 ? "time" : "times"}
          {answer.last_used ? ` · last on ${dateLabel(answer.last_used, false)}` : ""}
        </span>
      )}
      <div className="mt-auto flex flex-col gap-2 border-t border-jp-line-soft pt-4">
        <div className="flex items-center gap-2">
          {answer && (
            <Button variant="dangerLink" onClick={() => onDelete(answer)} disabled={saving}>
              Delete
            </Button>
          )}
          <span className="flex-1" />
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!ready || saving} onClick={() => onSave({ ...draft, question: draft.question.trim(), answer: draft.answer.trim(), city: draft.city.trim() })}>
            {saving ? "Saving…" : adding ? "Add answer" : "Save changes"}
          </Button>
        </div>
        <span className="text-label text-jp-ink-2">Saving makes a backup of answers.json, then re-indexes so the filler finds the new text.</span>
      </div>
    </Drawer>
  );
}
