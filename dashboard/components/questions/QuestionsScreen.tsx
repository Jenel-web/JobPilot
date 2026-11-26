"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { useEngine } from "@/components/shell/EngineProvider";
import { Banner } from "@/components/ui/Banner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusLine } from "@/components/ui/StatusLine";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { ApiError, answerUnknown, approveWording, getAnswers, getUnknown, getWordings, rejectWording } from "@/lib/api";
import type { ChangeInfo, UnknownAnswerIn, UnknownQuestion, Wording } from "@/lib/api-types";
import { plural } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import { AnsweredTab } from "./AnsweredTab";
import { WaitingTab } from "./WaitingTab";
import { WordingsTab } from "./WordingsTab";

type TabId = "waiting" | "wordings" | "answered";
type Notice = { tone: "amber" | "danger"; message: string; action: "dismiss" | "reload" };

/**
 * Questions (SPEC Part 2, sections 2 and 2b; design/screens/Questions.html): Waiting | Wordings | Answered.
 *
 * Every change goes through the engine, which backs up answers.json, saves, and re-indexes before it answers.
 * So while a request is out, the screen says "Re-indexing the answer bank…"; a re-index that could not run
 * comes back as a warning (amber Banner), never as a failure, because the change itself is saved.
 */
export function QuestionsScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const { refresh } = useEngine();
  const { showToast } = useToast();
  const unknown = usePoll(getUnknown);
  const wordings = usePoll(getWordings);
  const answers = usePoll(getAnswers);

  const urlTab = params.get("tab");
  const [tab, setTab] = useState<TabId>(urlTab === "wordings" || urlTab === "answered" ? urlTab : "waiting");
  const focusId = Number(params.get("id")) || null;
  const [busy, setBusy] = useState<number | null>(null); // the id of the row whose change is in flight
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirm, setConfirm] = useState<Wording | null>(null);

  const reloadAll = useCallback(async () => {
    await Promise.all([unknown.reload(), wordings.reload(), answers.reload()]);
    refresh();
  }, [unknown, wordings, answers, refresh]);

  const changeTab = (id: string) => {
    setTab(id as TabId);
    router.replace(id === "waiting" ? "/questions" : `/questions?tab=${id}`, { scroll: false });
  };

  /** Run one change: busy line while it runs, Toast after, warning or error Banner when needed. */
  async function run<T extends ChangeInfo>(id: number, change: () => Promise<T>, done: string): Promise<T | null> {
    setBusy(id);
    setNotice(null);
    try {
      const result = await change();
      showToast(done);
      if (result.warning && !result.reindexed) setNotice({ tone: "amber", message: result.warning, action: "dismiss" });
      return result;
    } catch (e) {
      if (e instanceof ApiError && e.code === "protected_needs_confirmation") throw e;
      setNotice({ tone: "danger", message: e instanceof Error ? e.message : String(e), action: "reload" });
      return null;
    } finally {
      setBusy(null);
      await reloadAll();
    }
  }

  const saveUnknown = (q: UnknownQuestion, body: UnknownAnswerIn) =>
    void run(q.id, () => answerUnknown(q.id, body), "Saved to answers.json (backup made)");

  const approve = async (w: Wording, confirmed: boolean) => {
    if ((w.protected || w.kind === "protected") && !confirmed) {
      setConfirm(w);
      return;
    }
    try {
      await run(w.id, () => approveWording(w.id, confirmed), "Added to answers.json (backup made)");
    } catch {
      setConfirm(w); // the engine found the saved answer is protected: ask, then send the confirmation
    }
  };

  const reject = (w: Wording) =>
    void run(w.id, () => rejectWording(w.id), "Rejected. This wording won't be suggested again.");

  const nUnknown = unknown.data?.length ?? 0;
  const nWordings = wordings.data?.length ?? 0;
  const loadError = unknown.error ?? wordings.error ?? answers.error;
  const loaded = unknown.data && wordings.data && answers.data;

  const subtitle =
    tab === "wordings"
      ? nWordings
        ? `${plural(nWordings, "new wording")} waiting · most seen first`
        : "No new wordings waiting"
      : `${nUnknown} waiting · ${plural(nWordings, "new wording")} to check`;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Questions"
        subtitle={loaded ? subtitle : "Loading…"}
        actions={
          <Tabs
            variant="boxed"
            active={tab}
            onChange={changeTab}
            tabs={[
              { id: "waiting", label: `Waiting (${nUnknown})` },
              { id: "wordings", label: `Wordings (${nWordings})` },
              { id: "answered", label: `Answered (${answers.data?.length ?? 0})` },
            ]}
          />
        }
      />

      {notice && (
        <Banner
          tone={notice.tone}
          message={notice.message}
          actionLabel={notice.action === "reload" ? "Reload" : "Got it"}
          onAction={() => {
            setNotice(null);
            if (notice.action === "reload") void reloadAll();
          }}
        />
      )}
      {loadError && loadError.code !== "engine_unreachable" && !notice && (
        <Banner tone="danger" message={loadError.message} actionLabel="Reload" onAction={() => void reloadAll()} />
      )}
      {busy !== null && <StatusLine tone="busy">Saving and re-indexing the answer bank…</StatusLine>}

      {loaded && tab === "waiting" && (
        <WaitingTab items={unknown.data!} saving={busy !== null} focusId={focusId} onSave={saveUnknown} />
      )}
      {loaded && tab === "wordings" && (
        <WordingsTab
          items={wordings.data!}
          answers={answers.data!}
          busyId={busy}
          onApprove={(w) => void approve(w, false)}
          onReject={reject}
          onShowAnswered={() => changeTab("answered")}
        />
      )}
      {loaded && tab === "answered" && <AnsweredTab answers={answers.data!} />}

      <ConfirmDialog
        open={confirm !== null}
        title="Approve a protected wording?"
        confirmLabel="Yes, they mean the same"
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          const w = confirm!;
          setConfirm(null);
          void approve(w, true);
        }}
      >
        {confirm && (
          <div className="flex flex-col gap-3 text-jp-ink">
            <p>This answer is protected. Do you confirm both questions mean exactly the same?</p>
            <div className="rounded-control border border-jp-line bg-jp-ground px-3.5 py-3 leading-normal">
              <b className="font-semibold">New:</b> {confirm.wording}
              <br />
              <b className="font-semibold">Saved:</b> {confirm.matched_question}
            </div>
            <p>If you confirm:</p>
            <ul className="list-disc pl-5 leading-relaxed">
              <li>
                The new wording is added to <b className="font-semibold">answers.json</b> (a backup is made first).
              </li>
              <li>It will be answered with your saved protected answer, word for word.</li>
              <li>The engine re-indexes the answer bank.</li>
            </ul>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
