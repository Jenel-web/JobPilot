import Link from "next/link";
import { ApplicationsChart } from "@/components/home/ApplicationsChart";
import { Funnel } from "@/components/home/Funnel";
import { RunOnceButton } from "@/components/home/RunOnceButton";
import { AlertRow } from "@/components/ui/AlertRow";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard } from "@/components/ui/StatCard";
import { StatusChip } from "@/components/ui/StatusChip";
import { cn } from "@/lib/cn";
import { applicationsPerDay, funnel, greeting, needsYou, recentActivity, stats } from "@/lib/mock/home";
import { reviewQueue } from "@/lib/mock/review";
import { scoreTextClass } from "@/lib/score";

export const metadata = { title: "Home · JobPilot" };

/** Home: the morning check. What happened, what needs me, how is the search going. (design/screens/Home.html) */
export default function HomePage() {
  const topMatches = reviewQueue.slice(0, 3);
  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={`Good morning, ${greeting.name}`} subtitle={greeting.summary} actions={<RunOnceButton />} />

      {needsYou.length > 0 && (
        <div className="flex flex-col gap-2">
          {needsYou.map((n) => (
            <AlertRow key={n.id} {...n} />
          ))}
        </div>
      )}

      <div className="grid grid-cols-4 gap-3.5">
        {stats.map((s) => (
          <StatCard key={s.label} {...s} />
        ))}
      </div>

      <div className="grid grid-cols-[60fr_40fr] gap-3.5">
        <ApplicationsChart days={applicationsPerDay} />
        <Funnel steps={funnel} />
      </div>

      <div className="grid grid-cols-2 gap-3.5">
        <section className="flex flex-col gap-1.5 rounded-card border border-jp-line bg-jp-surface px-[18px] py-4 text-sm">
          <span className="mb-1 font-semibold">Top matches today</span>
          {topMatches.map((job, i) => (
            <Link
              key={job.id}
              href="/review"
              className={cn(
                "grid grid-cols-[40px_1fr_auto] items-center gap-3 py-1.5",
                i < topMatches.length - 1 && "border-b border-jp-line-soft",
              )}
            >
              <span className={cn("tabular font-semibold", scoreTextClass(job.score))}>{job.score}</span>
              <span>
                {job.title}, {job.company} <span className="text-jp-ink-2">· {job.location}</span>
              </span>
              <StatusChip status="queued" size="sm" />
            </Link>
          ))}
        </section>

        <section className="flex flex-col gap-1.5 rounded-card border border-jp-line bg-jp-surface px-[18px] py-4 text-sm">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-semibold">Recent activity</span>
            <Link href="/activity" className="text-label font-medium text-jp-brand">
              See all
            </Link>
          </div>
          {recentActivity.map((a, i) => (
            <div
              key={a.id}
              className={cn("flex gap-3 py-1.5", i < recentActivity.length - 1 && "border-b border-jp-line-soft")}
            >
              <span className="tabular w-[70px] text-jp-ink-2">{a.time}</span>
              <span>{a.text}</span>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
