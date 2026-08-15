import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Ban } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RoleGate } from "@/layout/RoleGate";
import { JobProgressBar, elapsed, useNow } from "@/components/JobProgressBar";
import { getJob, cancelJob } from "@/api/jobs";
import { errorMessage } from "@/lib/errors";
import { formatDateTime, titleCase } from "@/lib/format";

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  if (!jobId) return null;

  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelJob(jobId),
    onSuccess: () => {
      toast.success("Job cancelled");
      void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const job = jobQuery.data;
  const canCancel = job && (job.status === "pending" || job.status === "running");
  const inProgress = job?.status === "pending" || job?.status === "running";
  const now = useNow(inProgress ?? false);

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2 -ml-2" onClick={() => navigate("/jobs")}>
        <ArrowLeft className="h-4 w-4" />
        Back to jobs
      </Button>

      <QueryState isLoading={jobQuery.isLoading} isError={jobQuery.isError} error={jobQuery.error}>
        {job && (
          <>
            <PageHeader
              title={titleCase(job.job_type)}
              description={`Target: ${titleCase(job.target_type)}`}
              actions={
                canCancel && (
                  <RoleGate minRole="operator">
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={cancelMutation.isPending}
                      onClick={() => cancelMutation.mutate()}
                    >
                      <Ban className="h-4 w-4" />
                      Cancel
                    </Button>
                  </RoleGate>
                )
              }
            />

            <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <InfoItem label="Status" value={<StatusBadge value={job.status} />} />
              <InfoItem label="Created" value={formatDateTime(job.created_at)} />
              <InfoItem label="Started" value={formatDateTime(job.started_at)} />
              <InfoItem label="Finished" value={formatDateTime(job.finished_at)} />
            </div>

            {inProgress && (
              <div className="mb-6 flex flex-col gap-1.5">
                <p className="text-xs text-muted-foreground">
                  {job.status === "pending" ? "waiting to start…" : `running… ${elapsed(job.started_at, now)}`}
                </p>
                <JobProgressBar job={job} now={now} />
              </div>
            )}

            {job.server_ids.length > 0 && (
              <Card className="mb-6">
                <CardHeader>
                  <CardTitle className="text-sm">Target servers ({job.server_ids.length})</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-1.5">
                  {job.server_ids.map((id) => (
                    <Badge key={id} variant="outline" className="font-mono text-xs">
                      {id.slice(0, 8)}
                    </Badge>
                  ))}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Log output</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="log-viewer max-h-[60vh] overflow-y-auto rounded-md bg-muted p-4">
                  {job.log_output || (job.status === "pending" ? "waiting to start…" : "(no output)")}
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </QueryState>
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-0.5 text-sm font-medium">{value}</div>
    </div>
  );
}
