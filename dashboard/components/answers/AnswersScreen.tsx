"use client";

import { useMemo, useState } from "react";
import { useEngine } from "@/components/shell/EngineProvider";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { FilterChip } from "@/components/ui/FilterChip";
import { PageHeader } from "@/components/ui/PageHeader";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusChip } from "@/components/ui/StatusChip";
import { StatusLine } from "@/components/ui/StatusLine";
import { useToast } from "@/components/ui/Toast";
import { ApiError, addAnswer, deleteAnswer, getAnswers, updateAnswer } from "@/lib/api";
import type { ChangeInfo, Kind, SavedAnswer } from "@/lib/api-types";
import { dateLabel } from "@/lib/format";
import { scopeLabel } from "@/lib/labels";
import { usePoll } from "@/lib/usePoll";
import { AnswerDrawer, type AnswerDraft } from "./AnswerDrawer";

type KindFilter = "all" | Kind;
type Pending =
  | { type: "save"; answer: SavedAnswer; draft: AnswerDraft }
  | { type: "delete"; answer: SavedAnswer };

/** Does this answer match the search text? Looks at the question, the answer and the approved wordings. */
function matches(a: SavedAnswer, text: string): boolean {
  if (!text) return true;
  const hay = `${a.question} ${a.answer} ${a.also_asked_as.join(" ")}`.toLowerCase();
  return hay.includes(text.toLowerCase());
}

/**
 * Answer bank editor (SPEC Part 2, section 3; design/screens/AnswerBank.html): search, filter by kind, add,
 * edit and delete. Every change goes through the engine (backup of answers.json, save, re-index). A change to
 * a protected answer, and every delete, asks first in a ConfirmDialog.
 */
export function AnswersScreen() {
  const answers = usePoll(getAnswers);
  const { refresh } = useEngine();
  const { showToast } = useToast();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [open, setOpen] = useState<SavedAnswer | "new" | null>(null);
  const [saving, setSaving] = useState(false);
  const [drawerError, setDrawerError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);

  const all = useMemo(() => answers.data ?? [], [answers.data]);
  const rows = all.filter((a) => (kind === "all" || a.kind === kind) && matches(a, search.trim()));
  const count = (k: KindFilter) => (k === "all" ? all.length : all.filter((a) => a.kind === k).length);

  function closeDrawer() {
    setOpen(null);
    setDrawerError(null);
  }

  /** Send one change; on success close the drawer, Toast, and warn if the re-index could not run. */
  async function send(change: () => Promise<ChangeInfo>, done: string) {
    setSaving(true);
    setDrawerError(null);
    setWarning(null);
    try {
      const result = await change();
      closeDrawer();
      showToast(done);
      if (result.warning && !result.reindexed) setWarning(result.warning);
    } catch (e) {
      if (e instanceof ApiError && e.code === "protected_needs_confirmation" && open && open !== "new") {
        throw e; // the caller asks for confirmation
      }
      setDrawerError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
      await answers.reload();
      refresh();
    }
  }

  function save(draft: AnswerDraft, confirmed = false) {
    if (open === "new" || open === null) {
      void send(() => addAnswer(draft), "Saved to answers.json (backup made)");
      return;
    }
    const current = open;
    if (current.kind === "protected" && !confirmed) {
      setPending({ type: "save", answer: current, draft });
      return;
    }
    send(
      () => updateAnswer(current.id, { answer: draft.answer, kind: draft.kind, scope: draft.scope, city: draft.city, confirm_protected: confirmed }),
      "Saved to answers.json (backup made)",
    ).catch(() => setPending({ type: "save", answer: current, draft }));
  }

  function remove(a: SavedAnswer) {
    void send(() => deleteAnswer(a.id, a.kind === "protected"), "Deleted (backup made)");
  }

  const columns: Column<SavedAnswer>[] = [
    {
      key: "q",
      header: "Question",
      width: "30fr",
      render: (a) => (
        <span className="flex flex-col gap-0.5">
          <b className="font-semibold">{a.question}</b>
          {a.also_asked_as.length > 0 && <span className="text-label text-jp-ink-2">Also asked as {a.also_asked_as.length}</span>}
        </span>
      ),
    },
    { key: "a", header: "Answer", width: "30fr", render: (a) => <span className="line-clamp-2" title={a.answer}>{a.answer}</span> },
    { key: "kind", header: "Kind", width: "10fr", render: (a) => <StatusChip status="new" label={a.kind} /> },
    { key: "scope", header: "Location scope", width: "14fr", render: (a) => scopeLabel(a) },
    { key: "used", header: "Used", width: "7fr", align: "right", render: (a) => a.times_used },
    {
      key: "last",
      header: "Last used",
      width: "9fr",
      render: (a) => <span className="text-label text-jp-ink-2">{a.last_used ? dateLabel(a.last_used, false) : "Never"}</span>,
    },
  ];

  const drawerAnswer = open === "new" ? null : open;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Answer bank"
        subtitle={answers.data ? `${all.length} saved answers · reused on every form, matched by meaning` : "Loading…"}
        actions={
          <Button variant="primary" onClick={() => setOpen("new")}>
            Add answer
          </Button>
        }
      />
      {warning && <Banner tone="amber" message={`Saved, but not re-indexed yet. ${warning}`} actionLabel="Got it" onAction={() => setWarning(null)} />}
      {answers.error && answers.error.code !== "engine_unreachable" && (
        <Banner tone="danger" message={answers.error.message} actionLabel="Reload" onAction={() => void answers.reload()} />
      )}
      {saving && <StatusLine tone="busy">Saving and re-indexing the answer bank…</StatusLine>}

      <div className="flex items-center gap-2">
        <SearchInput label="Search questions and answers" value={search} onChange={setSearch} />
        <span className="w-2" />
        {(["all", "fixed", "open", "protected"] as const).map((k) => (
          <FilterChip
            key={k}
            label={`${k === "all" ? "All" : k[0].toUpperCase() + k.slice(1)} ${count(k)}`}
            active={kind === k}
            onClick={() => setKind(k)}
          />
        ))}
      </div>

      {answers.data &&
        (rows.length === 0 ? (
          <EmptyState
            message={search ? `No saved answer matches "${search}". Search looks at questions, answers and other wordings.` : "No saved answers of this kind."}
            actionLabel={search ? "Clear search" : "Show all"}
            onAction={() => {
              setSearch("");
              setKind("all");
            }}
          />
        ) : (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(a) => String(a.id)}
            onRowClick={(a) => {
              setDrawerError(null);
              setOpen(a);
            }}
            selectedKey={drawerAnswer ? String(drawerAnswer.id) : null}
            tall
          />
        ))}

      {open !== null && (
        <AnswerDrawer
          key={open === "new" ? "new" : open.id}
          answer={drawerAnswer}
          open
          saving={saving}
          error={drawerError}
          onClose={closeDrawer}
          onSave={(draft) => save(draft)}
          onDelete={(a) => setPending({ type: "delete", answer: a })}
        />
      )}

      <ConfirmDialog
        open={pending?.type === "save"}
        title="Change a protected answer?"
        confirmLabel="Save protected answer"
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending?.type !== "save") return;
          const { draft } = pending;
          setPending(null);
          save(draft, true);
        }}
      >
        {pending?.type === "save" && (
          <div className="flex flex-col gap-3 text-jp-ink">
            <p>Protected answers are legal and eligibility answers. Every form that asks this question will get the new text, word for word.</p>
            <div className="rounded-control border border-jp-line bg-jp-ground px-3.5 py-3 leading-normal">
              <b className="font-semibold">Before:</b> {pending.answer.answer} ({pending.answer.kind})
              <br />
              <b className="font-semibold">After:</b> {pending.draft.answer} ({pending.draft.kind})
            </div>
            <p>If you confirm:</p>
            <ul className="list-disc pl-5 leading-relaxed">
              <li>
                A backup of <b className="font-semibold">answers.json</b> is made, then the change is saved.
              </li>
              <li>The engine re-indexes the answer bank.</li>
            </ul>
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pending?.type === "delete"}
        title="Delete this answer?"
        confirmLabel="Delete answer"
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending?.type !== "delete") return;
          const { answer } = pending;
          setPending(null);
          remove(answer);
        }}
      >
        {pending?.type === "delete" && (
          <div className="flex flex-col gap-3 text-jp-ink">
            <div className="rounded-control border border-jp-line bg-jp-ground px-3.5 py-3 leading-normal">
              <b className="font-semibold">{pending.answer.question}</b>
              <br />
              {pending.answer.answer} · {scopeLabel(pending.answer)}
            </div>
            <p>If you confirm:</p>
            <ul className="list-disc pl-5 leading-relaxed">
              <li>
                A backup of <b className="font-semibold">answers.json</b> is made, then the answer is removed.
              </li>
              <li>Forms that ask this question will flag it and add it to Questions again.</li>
              {pending.answer.kind === "protected" && (
                <li>This is a protected (legal) answer: forms will leave it empty until you answer it again.</li>
              )}
            </ul>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
