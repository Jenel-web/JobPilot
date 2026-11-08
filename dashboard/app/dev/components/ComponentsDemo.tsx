"use client";

import { useState } from "react";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { FilterChip } from "@/components/ui/FilterChip";
import { FlagMarker } from "@/components/ui/FlagMarker";
import { ModeBadge } from "@/components/ui/ModeBadge";
import { ScoreBadge } from "@/components/ui/ScoreBadge";
import { StatCard } from "@/components/ui/StatCard";
import { StatusChip } from "@/components/ui/StatusChip";
import { useToast } from "@/components/ui/Toast";
import type { Status } from "@/lib/types";

const STATUSES: Status[] = ["new", "queued", "approved", "submitted", "manual", "failed", "rejected", "interview", "offer"];

function Section({ title, blurb, children }: { title: string; blurb: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-card border border-jp-line bg-jp-surface p-6">
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="text-label leading-normal text-jp-ink-2">{blurb}</p>
      {children}
    </section>
  );
}

/** Every shared component in one place, to compare side by side with design/screens/Components.html. */
export function ComponentsDemo() {
  const { showToast } = useToast();
  const [dialog, setDialog] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [chip, setChip] = useState("All");

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <h1 className="font-serif text-[40px] font-medium leading-[1.1]">Components</h1>
        <p className="max-w-[760px] text-base leading-normal text-jp-ink-2">
          Built once and reused on Home, Review batch, Applications and Emails. Each one has a single job and the same
          name wherever it appears.
        </p>
      </div>

      <div className="grid grid-cols-2 items-start gap-10">
        <Section
          title="Status chip"
          blurb="Small pill, coloured by status. The text always states the status, so colour is never the only cue."
        >
          <div className="flex flex-wrap gap-2">
            {STATUSES.map((s) => (
              <StatusChip key={s} status={s} />
            ))}
          </div>
        </Section>

        <Section
          title="Score badge"
          blurb="A 0 to 100 score in a ring that fills to the value. Green at 80 and above, amber from 60 to 79, grey below 60."
        >
          <div className="flex items-center gap-7">
            {[
              [86, "80 and above"],
              [72, "60 to 79"],
              [41, "Under 60"],
            ].map(([score, caption]) => (
              <div key={score} className="flex flex-col items-start gap-2">
                <ScoreBadge score={score as number} size={48} />
                <span className="text-label text-jp-ink-2">{caption}</span>
              </div>
            ))}
          </div>
        </Section>

        <Section
          title="Mode badge"
          blurb="Shows what the engine is allowed to do. It sits in the top bar and opens Settings when clicked."
        >
          <div className="flex items-center gap-2.5">
            <ModeBadge mode="mock" />
            <ModeBadge mode="dry_run" />
            <ModeBadge mode="live" />
          </div>
          <div className="mt-1 flex items-center gap-2.5">
            <FlagMarker count={2} />
            <span className="text-label text-jp-ink-2">Flag marker: an answer was guessed by AI</span>
          </div>
        </Section>

        <Section
          title="Buttons"
          blurb={'One primary action per view. Labels name the result, such as "Submit approved (5)", not "Submit".'}
        >
          <div className="flex flex-wrap items-center gap-2.5">
            <Button variant="primary">Submit approved (5)</Button>
            <Button>Approve all unflagged</Button>
            <Button variant="primary" disabled>
              Submit approved (0)
            </Button>
            <Button variant="danger">Stop all actions</Button>
            <Button variant="link" href="#" external>
              Open on Prosple
            </Button>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="mr-1 text-label text-jp-ink-2">Filter chips</span>
            {["All", "Flagged only", "Score 80+"].map((c) => (
              <FilterChip key={c} label={c} active={chip === c} onClick={() => setChip(c)} />
            ))}
          </div>
        </Section>

        <Section
          title="Confirm dialog"
          blurb="Centred. Lists exactly what will happen. Risky actions use the red button and the cancel button is the default focus."
        >
          <div className="flex items-center gap-2.5">
            <Button onClick={() => setDialog(true)}>Open the dialog</Button>
            <span className="text-label text-jp-ink-2">Escape or Cancel closes it.</span>
          </div>
          <ConfirmDialog
            open={dialog}
            title="Submit 5 approved jobs?"
            confirmLabel="Submit 5 jobs"
            tone="primary"
            onCancel={() => setDialog(false)}
            onConfirm={() => {
              setDialog(false);
              showToast("5 jobs approved", "Saved");
            }}
          >
            Five applications and six emails will go out now. This cannot be undone.
          </ConfirmDialog>
        </Section>

        <Section
          title="Toast and banners"
          blurb="Toasts sit bottom-right and clear after 4 seconds. Banners stay until the problem is fixed and always carry one fix button."
        >
          <div className="flex flex-col gap-3">
            <div>
              <Button onClick={() => showToast("5 jobs approved", "Saved")}>Show a toast</Button>
            </div>
            <Banner tone="amber" message="Gemini quota used up. Switched to Ollama." actionLabel="View settings" />
            <Banner tone="danger" message="Stopped by you at 3:12 PM. Nothing will run." actionLabel="Resume" />
          </div>
        </Section>

        <Section title="Empty state" blurb="An icon, one sentence and one button. The sentence says what happens next.">
          <EmptyState
            message="Nothing to review. JobPilot will notify you when new matches are ready."
            actionLabel="Run once now"
          />
        </Section>

        <Section title="Stat card and drawer" blurb="Stat cards show one number. The drawer slides in from the right.">
          <div className="grid grid-cols-2 gap-3">
            <StatCard label="Found today" value={42} note="18 matched (score 60+)" />
            <StatCard label="Submitted this week" value={31} note="+8 vs last week" tone="good" />
          </div>
          <div>
            <Button onClick={() => setDrawer(true)}>Open the drawer</Button>
          </div>
          <Drawer
            open={drawer}
            onClose={() => setDrawer(false)}
            label="Example drawer"
            header={
              <>
                <span className="font-serif text-[22px] font-medium leading-[1.2]">Data Analyst Intern</span>
                <span className="text-label text-jp-ink-2">Appify · Taguig · Internship</span>
              </>
            }
          >
            <p className="text-sm text-jp-ink-2">Drawer content goes here.</p>
          </Drawer>
        </Section>
      </div>
    </div>
  );
}
