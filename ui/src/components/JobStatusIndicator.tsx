import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Loader2, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { JobProgressBar, elapsed, useNow } from "@/components/JobProgressBar";
import { getJob } from "@/api/jobs";

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
  if (!job) return null;

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

      {inProgress && <JobProgressBar job={job} now={now} />}

      {logOpen && (
        <div className="log-viewer max-h-40 overflow-y-auto rounded-md bg-muted p-2 text-xs">
          {job.log_output || (job.status === "pending" ? "waiting to start…" : "(no output)")}
        </div>
      )}
    </div>
  );
}
