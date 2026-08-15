import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listJobs, type JobRead } from "@/api/jobs";

// Ticks once a second purely to force a re-render — elapsed()/progress
// calculations are pure functions of Date.now(), so with no independent
// tick they only ever update when the 3s data poll happened to land, which
// reads as "frozen" between polls (worse if the tab was backgrounded and
// throttled polling further). The underlying Job keeps progressing
// regardless — Celery runs it independently of whether any browser has
// this open — this only fixes the on-screen clock, not the job itself.
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

export function elapsed(startedAt: string | null, now: number): string {
  if (!startedAt) return "";
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

// Aptly gives no real percent-complete signal for sync/publish/promote —
// it's a single blocking call with no progress stream (confirmed building
// the sync-status feature), so this fill is an ESTIMATE, not ground truth:
// it eases toward 95% over the average duration of this job's own past
// successful runs (same job_type, same target repository when there is
// one), then holds at 95% until the job actually finishes — never reports
// 100% before the real status does. No history yet -> caller falls back to
// an indeterminate sliding-chunk animation, since a fill with no duration
// to pace against would just be a made-up number.
export function useTypicalDurationMs(job: JobRead | undefined): number | null {
  const historyQuery = useQuery({
    queryKey: ["job-history-duration", job?.job_type, job?.repository_id],
    queryFn: () =>
      listJobs({
        job_type: job!.job_type,
        status: "success",
        repository_id: job!.repository_id ?? undefined,
        limit: 20,
      }),
    enabled: job !== undefined,
    staleTime: 60_000,
  });

  if (!historyQuery.data || !job) return null;
  const durationsMs = historyQuery.data
    .filter((j) => j.id !== job.id && j.started_at && j.finished_at)
    .map((j) => new Date(j.finished_at!).getTime() - new Date(j.started_at!).getTime());
  if (durationsMs.length === 0) return null;
  return durationsMs.reduce((sum, ms) => sum + ms, 0) / durationsMs.length;
}

// Eases toward (but never reaches) 95% over `typicalMs`, using an ease-out
// curve — fast early progress, slowing as it approaches the estimate,
// which reads as "still working" rather than stalling flat the way a
// linear ramp would once elapsed passes the average.
export function estimatedProgressPercent(elapsedMs: number, typicalMs: number): number {
  const ratio = Math.min(1, Math.max(0, elapsedMs / typicalMs));
  const eased = 1 - (1 - ratio) ** 2;
  return Math.min(95, eased * 95);
}

/** Renders the fill only — caller decides whether/when to show it
 * (typically `job.status === "pending" || job.status === "running"`). */
export function JobProgressBar({ job, now }: { job: JobRead; now: number }) {
  const typicalMs = useTypicalDurationMs(job);
  const progressPercent =
    job.status === "running" && job.started_at && typicalMs !== null
      ? estimatedProgressPercent(now - new Date(job.started_at).getTime(), typicalMs)
      : null;

  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Job progress">
      {progressPercent !== null ? (
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-1000 ease-linear"
          style={{ width: `${progressPercent}%` }}
        />
      ) : (
        // No duration history yet (new job type, or no successful runs to
        // average) — nothing to pace a fill against, so fall back to an
        // indeterminate sliding chunk rather than show a fabricated number.
        <div className="h-full w-1/3 animate-indeterminate rounded-full bg-primary" />
      )}
    </div>
  );
}
