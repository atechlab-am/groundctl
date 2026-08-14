import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Loader2, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { getJob, listJobs, type JobRead } from "@/api/jobs";

function elapsed(startedAt: string | null, now: number): string {
  if (!startedAt) return "";
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

// Ticks once a second purely to force a re-render — elapsed() itself is a
// pure function of Date.now(), so with no independent tick it only ever
// updated when the 3s data poll below happened to land, which reads as
// "frozen" between polls (worse if the tab was backgrounded and throttled
// polling further). The underlying Job keeps progressing regardless —
// Celery runs it independently of whether any browser has this open —
// this only fixes the on-screen clock, not the job itself.
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

// Aptly gives no real percent-complete signal for sync/delete/edit — it's
// a single blocking call with no progress stream (confirmed building the
// sync-status feature), so this fill is an ESTIMATE, not ground truth: it
// eases toward 95% over the average duration of this job's own past
// successful runs (same job_type, same target repository when there is
// one), then holds at 95% until the job actually finishes — never
// reports 100% before the real status does. No history yet -> falls back
// to the old indeterminate sliding-chunk animation, since a fill with no
// duration to pace against would just be a made-up number.
function useTypicalDurationMs(job: JobRead | undefined): number | null {
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

// Eases toward (but never reaches) 95% over `typicalMs`, using an
// ease-out curve — fast early progress, slowing as it approaches the
// estimate, which reads as "still working" rather than stalling flat the
// way a linear ramp would once elapsed passes the average.
function estimatedProgressPercent(elapsedMs: number, typicalMs: number): number {
  const ratio = Math.min(1, Math.max(0, elapsedMs / typicalMs));
  const eased = 1 - (1 - ratio) ** 2;
  return Math.min(95, eased * 95);
}

export function JobStatusIndicator({ jobId }: { jobId: string }) {
  const [logOpen, setLogOpen] = useState(false);

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });

  const job = jobQuery.data;
  const inProgress = job?.status === "pending" || job?.status === "running";
  const now = useNow(inProgress);
  const typicalMs = useTypicalDurationMs(inProgress ? job : undefined);
  if (!job) return null;

  const progressPercent =
    job.status === "running" && job.started_at && typicalMs !== null
      ? estimatedProgressPercent(now - new Date(job.started_at).getTime(), typicalMs)
      : null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 text-sm">
        {inProgress ? (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            <span className="text-muted-foreground">
              {job.status === "pending" ? "waiting to start…" : `running… ${elapsed(job.started_at, now)}`}
            </span>
          </>
        ) : (
          <StatusBadge value={job.status} />
        )}
        <Link to={`/jobs/${job.id}`} className="text-xs text-muted-foreground hover:underline">
          view job
        </Link>
        <Button
          variant="ghost"
          size="sm"
          className="h-5 gap-1 px-1.5 text-xs text-muted-foreground"
          onClick={() => setLogOpen((v) => !v)}
        >
          {logOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          log
        </Button>
      </div>

      {inProgress && (
        <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
          {progressPercent !== null ? (
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-1000 ease-linear"
              style={{ width: `${progressPercent}%` }}
            />
          ) : (
            // No duration history yet (new job type, or no successful runs
            // to average) — nothing to pace a fill against, so fall back
            // to the old indeterminate sliding chunk rather than show a
            // fabricated number.
            <div className="h-full w-1/3 animate-indeterminate rounded-full bg-primary" />
          )}
        </div>
      )}

      {logOpen && (
        <div className="log-viewer max-h-40 overflow-y-auto rounded-md bg-muted p-2 text-xs">
          {job.log_output || (job.status === "pending" ? "waiting to start…" : "(no output)")}
        </div>
      )}
    </div>
  );
}
